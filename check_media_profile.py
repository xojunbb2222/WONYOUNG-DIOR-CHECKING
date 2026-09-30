"""ONE-TIME: check whether a reported Instagram post is discoverable FROM the media profile.
Does not publish, edit data, or run a SERP search. One bounded Bright Data profile discovery.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import requests

ROOT = Path(__file__).resolve().parent
API = 'https://api.brightdata.com'
DATASET = 'gd_lk5ns7kz21pck8jpis'
PROFILE = 'https://www.instagram.com/mensfoliomy/'
TARGET = 'Dd347fCMAsJ'
LIMIT = 20
OUT = ROOT / 'profile-source-check.json'


def code(url):
    try:
        p = urlparse(str(url or ''))
        if p.hostname not in ('www.instagram.com','instagram.com'):
            return None
        seg = p.path.strip('/').split('/')
        return seg[1] if len(seg)==2 and seg[0] in ('p','reel','reels','tv') and seg[1] else None
    except ValueError:
        return None


def parse_content(response):
    t = response.text.strip()
    if not t:
        raise ValueError('The provider returned an empty response')
    try:
        obj = response.json()
        if isinstance(obj, list):
            return obj, None
        if isinstance(obj, dict):
            if isinstance(obj.get('data'), list):
                return obj['data'], None
            if isinstance(obj.get('records'), list):
                return obj['records'], None
            if obj.get('snapshot_id'):
                return [], str(obj['snapshot_id'])
            if obj.get('error'):
                raise ValueError('Provider error: ' + str(obj['error'])[:300])
            return [], None
    except requests.exceptions.JSONDecodeError:
        pass
    rows=[]
    for line in response.text.splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows, None


def main():
    result = {'time_utc':datetime.now(timezone.utc).isoformat(),
              'mode':'discover_new from exactly one Instagram profile',
              'profile':PROFILE,'max_requested_records':LIMIT,
              'target_shortcode':TARGET,'status':'starting', 'note':'Profile discovery is a second retrieval path, not fully independent proof of Instagram authorship.'}
    def save():
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    save()
    key = os.environ.get('BRIGHTDATA_API_KEY')
    if not key:
        result.update(status='configuration_error',error='BRIGHTDATA_API_KEY not configured');save();raise RuntimeError(result['error'])
    headers = {'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    session=requests.Session()
    params={'dataset_id': DATASET,'notify':'false','include_errors':'true','type':'discover_new','discover_by':'url'}
    data={'input':[{'url':PROFILE,'num_of_posts':LIMIT}]}
    try:
        response=session.post(API+'/datasets/v3/scrape',params=params,headers=headers,json=data,timeout=180)
        result['request_http']=response.status_code
        result['response_bytes']=len(response.content)
        response.raise_for_status()
        rows,snapshot=parse_content(response)
        if snapshot:
            result['snapshot_received']=True
            result['status']='waiting_for_snapshot';save()
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                info=session.get(API+'/datasets/v3/progress/'+snapshot,
                                 headers={'Authorization':'Bearer '+key},timeout=30)
                info.raise_for_status()
                state=str(info.json().get('status',''))
                if state=='ready':
                    ready=session.get(API+'/datasets/v3/snapshot/'+snapshot,
                                      params={'format':'json'},headers={'Authorization':'Bearer '+key},timeout=90)
                    ready.raise_for_status()
                    rows,_=parse_content(ready)
                    break
                if state=='failed':
                    raise ValueError('Profile discovery snapshot failed')
                time.sleep(12)
            else:
                result.update(status='still_processing',note='Provider job not ready yet. Do not rerun automatically: it could create a new paid job.');save();return
        if not isinstance(rows,list):
            raise ValueError('Invalid rows type')
        overview=[]
        for item in rows[:100]:
            if not isinstance(item,dict):continue
            url=str(item.get('url') or item.get('post_url') or '')
            overview.append({'shortcode':code(url),'url':url[:180],
                'author':str(item.get('user_posted') or item.get('account') or '')[:80],
                'date':str(item.get('date_posted') or '')[:35],
                'caption_excerpt':str(item.get('description') or '')[:130],
                'error':str(item.get('error') or '')[:120]})
        matches=[x for x in overview if x['shortcode']==TARGET]
        result.update({'status':'completed','records_returned':len(rows),
            'target_present_in_profile_results':bool(matches),
            'target_match':matches,
            'rows':overview,
            'interpretation':('Target found from profile route; corroborates association within Bright Data, but requires external confirmation.'
               if matches else 'Target absent from limited recent profile results; not proof it never belonged to this account.')})
        save()
        print('Profile returned:',len(rows),'target found:',bool(matches))
    except Exception as exc:
        result.update(status='error',error=type(exc).__name__+': '+str(exc)[:350]);save()
        raise


if __name__=='__main__':main()
