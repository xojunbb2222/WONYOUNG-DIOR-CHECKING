"""Publish explicitly reviewed media posts; no Bright Data calls.

This only checks the approval file against the existing review queue. Human reviewer
is responsible for confirming Instagram content and permalink in the browser.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def read(path,default):
    f=ROOT/path
    return json.loads(f.read_text(encoding='utf8')) if f.exists() else default

def write(path,obj):
    (ROOT/path).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf8')

def code(url):
    m=re.fullmatch(r'https://www\.instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]{5,})/?',str(url))
    return m.group(1) if m else None

def main():
    approved=read('approved-posts.json',{'approved':[]}).get('approved',[])
    if not isinstance(approved,list):raise ValueError('approved must be a list')
    queue=read('media-review-queue.json',[])
    existing=read('posts.json',{'posts':[]})
    trusted_file=read('trusted_media.json',{})
    trusted={x.lower() for x in trusted_file.get('accounts',[])}
    excluded={x.lower() for x in trusted_file.get('excluded_accounts',[])}
    by_id={str(x.get('id')):x for x in queue if isinstance(x,dict)}
    published={str(x.get('id')) for x in existing.get('posts',[])}
    count=0
    for item in approved:
        if not isinstance(item,dict) or item.get('reviewed') is not True:
            print('SKIP: not explicitly reviewed');continue
        ident=str(item.get('id',''));record=by_id.get(ident)
        if not record or ident in published:continue
        account=str(record.get('account') or '').lower()
        if not (ident==code(record.get('url'))==code(item.get('url')) and
                item.get('account')==record.get('account') and
                account in trusted and account not in excluded and
                str(record.get('date') or '')[:10]>='2026-09-27'):
            print('SKIP: invalid or mismatched review',ident);continue
        # Author and content were checked by the reviewer; no claim of automatic verification.
        row={k:record.get(k,'') for k in ('id','account','url','date','caption')}
        row.update({'review_status':'manually_verified','source':'manual_review'})
        existing.setdefault('posts',[]).append(row)
        published.add(ident);count+=1
    existing['posts'].sort(key=lambda x:str(x.get('date','')),reverse=True)
    existing['updated_at']=datetime.now(timezone.utc).date().isoformat()
    write('posts.json',existing)
    print('Approved entries:',len(approved),'published new:',count,'total:',len(existing['posts']))

if __name__=='__main__':main()
