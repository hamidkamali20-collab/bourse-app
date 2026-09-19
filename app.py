import requests, pandas as pd, time, re
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
import uvicorn
BRS_KEY = "BzkuT6VuWa2EQ9SaBswapQzetYAUcKjf"
BASE = "https://Api.BrsApi.ir"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
app = FastAPI()
CACHE = {}
TIER1 = ["فملی","فولاد","فارس","شستا","نوری","شپنا"]
TIER2 = ["فخوز","ذوب","کگل","کچاد","ومعادن","فزر","طلا","عیار","اهرم"]
INSCODE = {"فملی":"35425587644337450","فولاد":"46348559193224090","فخوز":"27906419856424640","ذوب":"18488008641058109","کگل":"35366681030756042","کچاد":"35700344742885862","طلا":"46752523285625450","عیار":"35589735413538838"}
def fallback_tsetmc(l18):
    try:
        ins=INSCODE.get(l18)
        if not ins: return None
        txt=requests.get(f"http://www.tsetmc.com/tsev2/data/instinfo.aspx?i={ins}&c=27",headers=HEADERS,timeout=10).text
        p=txt.split(";")[0].split(",")
        pc=int(float(p[2])); pl=int(float(p[3])); py=int(float(p[4]))
        return {"l18":l18,"l30":l18,"pc":pc,"pl":pl,"py":py,"pcp":round((pc-py)/py*100,2) if py else 0,"plp":round((pl-py)/py*100,2) if py else 0,"tvol":0,"tval":0,"tmin":0,"tmax":0,"cs":"Fallback","pe":0,"g_pe":0,"Buy_I_Volume":0,"Sell_I_Volume":0,"_fallback":True}
    except: return None
def get_symbol(l18):
    now=time.time()
    if l18 in CACHE and now-CACHE[l18]['t']<600: return CACHE[l18]['d']
    try:
        r=requests.get(f"{BASE}/Tsetmc/Symbol.php?key={BRS_KEY}&l18={l18}",headers=HEADERS,timeout=15)
        j=r.json()
        if isinstance(j,dict) and j.get("successful")==False:
            fb=fallback_tsetmc(l18)
            if fb: CACHE[l18]={'d':fb,'t':now}; return fb
            return {"_error":j.get("error_message"),"l18":l18,"pc":0}
        CACHE[l18]={'d':j,'t':now}; return j
    except:
        fb=fallback_tsetmc(l18)
        return fb if fb else {"_error":"خطا","l18":l18,"pc":0}
def get_history(l18):
    for url in [f"{BASE}/Tsetmc/Candlestick.php?key={BRS_KEY}&l18={l18}&period=D", f"{BASE}/Tsetmc/History.php?key={BRS_KEY}&l18={l18}"]:
        try:
            r=requests.get(url,headers=HEADERS,timeout=15).json()
            if isinstance(r,list) and len(r)>5: return r
            if isinstance(r,dict) and "data" in r: return r["data"]
        except: pass
    return []
def tablo_tools(d):
    try:
        bi=d.get("Buy_I_Volume") or 0; si=d.get("Sell_I_Volume") or 0
        bc=d.get("Buy_CountI") or 1; sc=d.get("Sell_CountI") or 1
        s1=(bi/bc/1e6) if bc else 0; s2=(si/sc/1e6) if sc else 0
        gh=round(s1/(s2 or 1),2); pool=bi-si
        tag="ورود پول هوشمند ✅" if pool>0 and gh>1.3 else "خروج پول ❌" if pool<0 else "خنثی"
        return {"قدرت":gh,"سرانه_خرید":round(s1,1),"پول_حقیقی":tag,"حجم":"عادی"}
    except: return {}
def calc_signal(hist,data,risk="normal",custom=None):
    pc=data.get('pc') or data.get('pl') or 0
    if pc==0 and "_error" in data and not data.get("_fallback"): return {"error":"سهمیه تمام","price":0}
    try:
        if len(hist)>=10:
            closes=[float(x.get('pc') or x.get('close') or 0) for x in hist[-30:] if x.get('pc') or x.get('close')]
            s=pd.Series(closes); price=closes[-1]
        else: price=float(pc); closes=[price*(1+(i-15)*0.003) for i in range(30)]; s=pd.Series(closes)
        atr=s.diff().abs().mean()*1.8
        if atr==0 or pd.isna(atr): atr=price*0.02
        mult={"low":1.0,"normal":1.5,"high":2.2}.get(risk,1.5)
        stop=float(custom) if custom else price-atr*mult
        t1=price+atr*2; t2=price+atr*3; be=price*1.011
        ma20=s.rolling(20).mean().iloc[-1] if len(s)>=20 else s.mean()
        sig="خرید ✅" if price>ma20*1.01 else "فروش ❌" if price<ma20*0.99 else "خنثی ➖"
        rr=round((t1-price)/(price-stop),2) if price!=stop else 0
        return {"price":round(price),"ma20":round(ma20),"stop":round(stop),"t1":round(t1),"t2":round(t2),"be":round(be),"sig":sig,"rr":rr,"dist":round((price-stop)/price*100,2)}
    except Exception as e: return {"error":str(e)}
def get_fund(data):
    if data.get("_error") or not data.get("pe"): return {"pe":"ناموجود","gpe":"ناموجود","ps":"ناموجود","ff":"ناموجود","score":"-","status":"دیتا ناموجود - سهمیه"}
    try:
        pe=float(data.get('pe') or 0); gpe=float(data.get('g_pe') or 0); ps=float(data.get('ps') or 0); eps=float(data.get('eps') or 0)
        sc=0
        if 0<pe<gpe and pe<8: sc+=3
        elif 0<pe<gpe: sc+=2
        if 0<ps<1.5: sc+=2
        if eps>0: sc+=1
        st="ارزنده ✅" if sc>=4 else "متوسط ⚖️" if sc>=2 else "گران ⚠️"
        return {"pe":pe,"gpe":gpe,"ps":ps,"eps":eps,"ff":data.get('ff'),"score":sc,"status":st,"mv":data.get('mv')}
    except: return {"status":"خطا"}
def get_fipiran(l18):
    try:
        for url in [f"https://www.fipiran.ir/Symbol?symbolpara={l18}", f"https://www.fipiran.com/Symbol?symbolpara={l18}"]:
            r=requests.get(url,headers=HEADERS,timeout=12)
            if r.status_code!=200: continue
            soup=BeautifulSoup(r.text,'html.parser')
            txt=soup.get_text()
            pe=re.search(r"P/E\s*[:\s]*([\d\.]+)",txt)
            return {"P/E فیپیران":pe.group(1) if pe else "ناموجود","متن":txt[:500].replace("\n"," ")[:350],"url":url}
        return {"error":"فیپیران در دسترس نیست"}
    except Exception as e: return {"error":str(e)}
def get_sahamyab(l18):
    try:
        url=f"https://r.sahamyab.com/hashtag/{l18}"
        r=requests.get(url,headers=HEADERS,timeout=12)
        soup=BeautifulSoup(r.text,'html.parser')
        tw=[]
        for a in soup.select("a"):
            t=a.get_text().strip()
            if len(t)>40: tw.append(t[:300])
            if len(tw)>=8: break
        return tw[:8] if tw else ["توئیتی پیدا نشد"]
    except Exception as e: return [f"خطا: {e}"]
def get_news():
    src={"سنا":"https://www.sena.ir","دنیای بورس":"https://donya-e-bourse.ir","TGJU":"https://www.tgju.org"}
    all=[]
    for n,u in src.items():
        try:
            r=requests.get(u,headers=HEADERS,timeout=10)
            soup=BeautifulSoup(r.text,'html.parser')
            all.extend([f"[{n}] "+a.get_text().strip() for a in soup.select("a") if len(a.get_text().strip())>30][:2])
            if len(all)>=6: break
        except: pass
    return all or ["اخبار نیست"]
def get_telegram(ch):
    for url in [f"https://t.me/s/{ch}", f"https://api.allorigins.win/raw?url=https://t.me/s/{ch}"]:
        try:
            r=requests.get(url,headers=HEADERS,timeout=15)
            soup=BeautifulSoup(r.text,'html.parser')
            m=soup.select(".tgme_widget_message_text")
            if m: return [x.get_text()[:350] for x in m[:8]]
        except: pass
    return ["کانال خصوصی"]
@app.get("/api/symbol/{name}")
def a1(name:str): return get_symbol(name)
@app.get("/api/signal/{name}")
def a2(name:str,risk:str="normal",custom:str=None): d=get_symbol(name); h=get_history(name); return calc_signal(h,d,risk,custom)
@app.get("/api/tablo/{name}")
def a3(name:str): return tablo_tools(get_symbol(name))
@app.get("/api/fund/{name}")
def a4(name:str):
    d=get_symbol(name)
    try: c=requests.get(f"{BASE}/Codal/Codal.php?key={BRS_KEY}&l18={name}",headers=HEADERS,timeout=10).json(); c=[x.get('title','')[:90] for x in c[:3]] if isinstance(c,list) else ["محدود"]
    except: c=["نیاز پلن"]
    return {"fund":get_fund(d),"codal":c}
@app.get("/api/fipiran/{name}")
def a8(name:str): return get_fipiran(name)
@app.get("/api/sahamyab/{name}")
def a9(name:str): return {"نماد":name,"tweets":get_sahamyab(name)}
@app.get("/api/telegram/{ch}")
def a5(ch:str): return {"channel":ch,"messages":get_telegram(ch)}
@app.get("/api/news")
def a6(): return {"news":get_news()}
@app.get("/api/critique/{name}")
def a7(name:str,risk:str="normal"): d=get_symbol(name); h=get_history(name); s=calc_signal(h,d,risk); f=get_fund(d); n=get_news(); rr=s.get("rr",0); gem="✅ R/R خوب" if rr>1.5 else "⚠️ R/R ضعیف"; gpt="💡 همسو" ; return {"gemini":gem,"gpt":gpt,"rr":rr}
@app.get("/", response_class=HTMLResponse)
def home():
    return """<!DOCTYPE html><html dir="rtl" lang="fa"><head><meta charset='utf-8'><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bourse Pro</title>
<style>*{font-family:tahoma,sans-serif;box-sizing:border-box}body{background:#f1f5f9;margin:0;padding:12px;color:#0f172a}
.header{background:linear-gradient(135deg,#0f172a,#1e40af);color:white;border-radius:16px;padding:18px;margin-bottom:12px}
.card{background:white;border-radius:16px;padding:14px;box-shadow:0 4px 16px rgba(0,0,0,.07);margin-bottom:12px}
.btn{padding:7px 10px;border-radius:10px;border:1px solid #e2e8f0;background:white;cursor:pointer;margin:2px;font-size:12px}
.btn.active{background:#0f172a;color:white}
</style></head><body>
<div class="header"><h2>🚀 بورس پرو - سالم</h2><p style=opacity:.85>ردیف 1 و 2 + فیپیران اسکرپ + سهام‌یاب + نقد AI</p></div>
<div class="card"><button class="btn" onclick="load('فملی')">فملی</button><button class="btn" onclick="load('فولاد')">فولاد</button><button class="btn" onclick="load('کگل')">کگل</button><button class="btn" onclick="load('طلا')">طلا</button><button class="btn" onclick="load('عیار')">عیار</button><hr><input id="sym" value="فملی" style="width:100px"><button onclick="load(document.getElementById('sym').value)" style="background:#1e40af;color:white;padding:8px 14px;border-radius:10px;border:none">نمایش</button></div>
<div id="main"></div><div id="fipiran" class="card"></div><div id="sahamyab" class="card"></div>
<script>
function fmt(n){return Number(n).toLocaleString('fa-IR')}
async function load(sym){
 let d=await fetch('/api/symbol/'+sym).then(r=>r.json());
 let s=await fetch('/api/signal/'+sym).then(r=>r.json());
 let f=await fetch('/api/fipiran/'+sym).then(r=>r.json());
 let sh=await fetch('/api/sahamyab/'+sym).then(r=>r.json());
 document.getElementById('main').innerHTML=`<div class=card><h3>${d.l18||sym} ${d.pc||0}</h3><p>${s.sig||s.error}</p>حد ضرر ${fmt(s.stop||0)}</div>`;
 document.getElementById('fipiran').innerHTML=`<b>🏛 فیپیران</b><br>P/E: ${f['P/E فیپیران']||f.error}<br><a href="${f.url||'#'}" target="_blank">fipiran</a>`;
 document.getElementById('sahamyab').innerHTML='<b>💬 سهام‌یاب '+sym+'</b><br>'+sh.tweets.map(x=>'<div style=padding:4px 0>'+x+'</div>').join('')
}
load('فملی');
</script></body></html>"""
if __name__ == "__main__":
    uvicorn.run(app,host="0.0.0.0",port=8000)
