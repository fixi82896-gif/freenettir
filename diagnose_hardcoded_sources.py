"""Read-only audit of the source lists in main.py; no credentials and no bot posts."""
import ast
import concurrent.futures
import json
import requests
from main import extract_configs_from_text
from proxy_utils import extract_proxy_links, extract_socks5_endpoints
from proxy_health import is_live_mtproto

def find_lists():
    tree=ast.parse(open("main.py",encoding="utf-8").read())
    found={}
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign):
            for t in node.targets:
                if isinstance(t,ast.Name) and t.id in ("base_github_sources","base_proxy_sources"):
                    found[t.id]=ast.literal_eval(node.value)
    return found

def one(kind,url):
    r={"category":kind,"url":url}
    try:
        resp=requests.get(url,timeout=14,headers={"User-Agent":"Mozilla/5.0 (compatible; SourceAuditor/1.0)"})
        r["status"]=resp.status_code
        if resp.status_code != 200:
            r["result"]="HTTP_ERROR"
            return r
        if kind=="config":
            cfgs=extract_configs_from_text(resp.text)
            r["extracted"]=len(cfgs)
            r["result"]="PARSEABLE" if cfgs else "NO_MATCHING_CONFIGS"
        else:
            px=extract_proxy_links(resp.text)
            socks=extract_socks5_endpoints(resp.text)
            mt=[u for u in px if "/proxy?" in u]
            r["mtproto_links"]=len(mt)
            r["socks_links"]=sum("/socks?" in u for u in px)+len(socks)
            r["verified"]=sum(is_live_mtproto(u) for u in mt[:4])
            r["tested"]=min(4,len(mt))
            r["result"]=("MT_VERIFIED" if r["verified"] else "NO_VERIFIED_MT")
    except Exception as ex:
        r["result"]="REQUEST_FAILED"
        r["error_type"]=type(ex).__name__
    return r

if __name__=="__main__":
    d=find_lists()
    print("START_SOURCE_AUDIT",flush=True)
    jobs=[("config",u) for u in d["base_github_sources"]]+[("proxy",u) for u in d["base_proxy_sources"]]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures={pool.submit(one,k,url):(k,url) for k,url in jobs}
        results=[f.result() for f in concurrent.futures.as_completed(futures)]
    for item in sorted(results,key=lambda x:(x["category"],x["url"])):
        print("SOURCE_AUDIT "+json.dumps(item,ensure_ascii=False,sort_keys=True),flush=True)
    print("END_SOURCE_AUDIT",flush=True)
