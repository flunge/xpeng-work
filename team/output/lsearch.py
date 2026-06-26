import sys,json,subprocess,re
def search(q,n=12):
    r=subprocess.run(["lark-cli","docs","+search","--query",q,"--as","user"],capture_output=True,text=True,timeout=60)
    try: d=json.loads(r.stdout)
    except: return []
    out=[]
    for x in d.get('data',{}).get('results',[]):
        m=x.get('result_meta',{})
        t=re.sub(r'</?[^>]+>','',x.get('title_highlighted','') or '')
        out.append((m.get('doc_types'),m.get('token'),t,m.get('owner_name'),(m.get('update_time_iso') or '')[:10]))
    return out[:n]
if __name__=='__main__':
    q=sys.argv[1]; n=int(sys.argv[2]) if len(sys.argv)>2 else 12
    for dt,tok,t,o,u in search(q,n):
        print(f'{dt:5}|{tok}|{u}|{o}|{t}')
