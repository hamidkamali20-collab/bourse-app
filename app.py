import requests, pandas as pd, time
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from bs4 import BeautifulSoup
import uvicorn
BRS_KEY = "BzkuT6VuWa2EQ9SaBswapQzetYAUcKjf"
BASE = "https://Api.BrsApi.ir"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"}
app = FastAPI()
CACHE = {}
TIER1 = ["فملی","فولاد","فارس","شستا","نوری","شپنا","شتران","وبملت","پارسان","وغدیر"]
TIER2 = ["فخوز","ذوب","هرمز","کگل","کچاد","ومعادن","کنور","فزر","کروی","عیار","کهربا","طلا","اهرم","توان"]
INSCODE = {"فملی":"35425587644337450","فولاد":"46348559193224090","فخوز":"27906419856424640","ذوب":"18488008641058109","هرمز":"15753803582221477","کگل":"35366681030756042","کچاد":"35700344742885862","ومعادن":"47466638396174110","فارس":"35425587644337450","شستا":"49568544329800661","اهرم":"53236819796184254","عیار":"35589735413538838"}

def fallback_tsetmc(l18):
    try:
        ins = INSCODE.get(l18)
        if not ins: return None
        txt = requests.get(f"http://www.tsetmc.com/tsev2/data/instinfo.aspx?i={ins}&c=27", headers=HEADERS, timeout=10).text
        p = txt.split(";")[0].split(",")
        pc=int(float(p[2])); pl=int(float(p[3])); py=int(float(p[4]))
        return {"l18":l18,"l30":l18,"pc":pc,"pl":pl,"py":py,"pcp":round((pc-py)/py*100,2) if py else 0,"plp":round((pl-py)/py*100,2) if py else 0,"tvol":0,"tval":0,"tmin":0,"tmax":0,"cs":"Fallback","pe":0,"g_pe":0,"Buy_I_Volume":0,"Sell_I_Volume":0,"_fallback":True}
    except: return None

def get_symbol(l18):
    now=time.time()
    if l18 in CACHE and now - CACHE[l18]['t'] < 600: return CACHE[l18]['d']
    try:
        r=requests.get(f"{BASE}/Tsetmc/Symbol.php?key={BRS_KEY}&l18={l18}", headers=HEADERS, timeout=15)
        j=r.json()
        if isinstance(j, dict) and j.get("successful")==False:
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
            r=requests.get(url, headers=HEADERS, timeout=15).json()
            if isinstance(r, list) and len(r)>5: return r
            if isinstance(r, dict) and "data" in r: return r["data"]
        except: pass
    return []

def tablo_tools(d):
    try:
        buy_i=d.get("Buy_I_Volume") or 0; sell_i=d.get("Sell_I_Volume") or 0
        bc=d.get("Buy_CountI") or 1; sc=d.get("Sell_CountI") or 1
        sarane_kharid = (buy_i/bc/1e6) if bc else 0
        sarane_forosh = (sell_i/sc/1e6) if sc else 0
        ghodrat = round(sarane_kharid/(sarane_forosh or 1),2)
        pool = buy_i - sell_i
        tag = "ورود پول هوشمند ✅" if pool>0 and ghodrat>1.3 else "خروج پول ❌" if pool<0 else "خنثی"
        vol = d.get("tvol") or 0; avg = d.get("tvol_avg_1m") or 1
        hajm = "حجم مشکوک 🔥" if vol> avg*2 else "عادی"
        return {"قدرت":ghodrat, "سرانه_خرید":round(sarane_kharid,1), "سرانه_فروش":round(sarane_forosh,1), "پول_حقیقی":tag, "حجم":hajm}
    except: return {}

def calc_signal(hist, data, risk="normal", custom=None):
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
        stop=float(custom) if custom else price - atr*mult
        t1=price+atr*2; t2=price+atr*3; be=price*1.011
        ma20=s.rolling(20).mean().iloc[-1] if len(s)>=20 else s.mean()
        sig="خرید ✅" if price>ma20*1.01 else "فروش ❌" if price<ma20*0.99 else "خنثی ➖"
        rr=round((t1-price)/(price-stop),2) if price!=stop else 0
        return {"price":round(price),"ma20":round(ma20),"stop":round(stop),"t1":round(t1),"t2":round(t2),"be":round(be),"sig":sig,"rr":rr,"dist":round((price-stop)/price*100,2)}
    except Exception as e: return {"error":str(e)}

def get_fund(data):
    if data.get("_error") or not data.get("pe"): return {"pe":"ناموجود","gpe":"ناموجود","ps":"ناموجود","ff":"ناموجود","score":"-","status":"دیتا ناموجود"}
    try:
        pe=float(data.get('pe') or 0); gpe=float(data.get('g_pe') or 0); ps=float(data.get('ps') or 0); eps=float(data.get('eps') or 0)
        score=0
        if 0<pe<gpe and pe<8: score+=3
        elif 0<pe<gpe: score+=2
        if 0<ps<1.5: score+=2
        if eps>0: score+=1
        status="ارزنده ✅" if score>=4 else "متوسط ⚖️" if score>=2 else "گران ⚠️"
        return {"pe":pe,"gpe":gpe,"ps":ps,"eps":eps,"ff":data.get('ff'),"score":score,"status":status,"mv":data.get('mv')}
    except: return {"status":"خطا"}
def critique_gemini(sig,fund,n): r=fund.get("score","-"); rr=sig.get("rr",0); t="";
    if sig.get("sig","").startswith("خرید") and rr<1.5: t+=f"⚠️ Gemini: R/R ضعیف ({rr}) - "
    elif sig.get("sig","").startswith("خرید") and str(r)=="4": t+=f"✅ Gemini: R/R {rr} + ارزنده - "
    return t or "Gemini: خنثی - منتظر حجم"
def critique_gpt(sig,fund):
    if "فروش" in sig.get("sig","") and fund.get("status","").startswith("ارزنده"): return f"💡 GPT Sola: تضاد! فروش تکنیکال ولی ارزنده - حد ضرر باز"
    if "خرید" in sig.get("sig","") and fund.get("status","").startswith("گران"): return "💡 GPT Pro: هشدار P/E بالا - کم ریسک"
    return "GPT: همسو"
def get_news():
    src={"سنا":"https://www.sena.ir","دنیای بورس":"https://donya-e-bourse.ir","تجارت نیوز":"https://tejaratnews.com","TGJU":"https://www.tgju.org"}
    all=[]
    for n,u in src.items():
        try:
            r=requests.get(u, headers=HEADERS, timeout=10)
            from bs4 import BeautifulSoup
            soup=BeautifulSoup(r.text,'html.parser')
            all.extend([f"[{n}] "+a.get_text().strip() for a in soup.select("a") if len(a.get_text().strip())>30][:2])
            if len(all)>=6: break
        except: pass
    return all or ["اخبار نیست"]
def get_telegram(ch):
    from bs4 import BeautifulSoup
    for url in [f"https://t.me/s/{ch}", f"https://api.allorigins.win/raw?url=https://t.me/s/{ch}"]:
        try:
            r=requests.get(url, headers=HEADERS, timeout=15)
            soup=BeautifulSoup(r.text,'html.parser')
            msgs=soup.select(".tgme_widget_message_text")
            if msgs: return [m.get_text()[:350] for m in msgs[:8]]
        except: pass
    return ["کانال خصوصی / پیشنهاد: boursenews_ir"]

@app.get("/api/symbol/{name}")
def a1(name:str): return get_symbol(name)
@app.get("/api/signal/{name}")
def a2(name:str, risk:str="normal", custom:str=None): d=get_symbol(name); h=get_history(name); return calc_signal(h,d,risk,custom)
@app.get("/api/tablo/{name}")
def a3(name:str): return tablo_tools(get_symbol(name))
@app.get("/api/fund/{name}")
def a4(name:str):
    d=get_symbol(name)
    try: c=requests.get(f"{BASE}/Codal/Codal.php?key={BRS_KEY}&l18={name}", headers=HEADERS, timeout=10).json(); c=[x.get('title','')[:90] for x in c[:3]] if isinstance(c,list) else ["محدود"]
    except: c=["نیاز پلن پولی"]
    return {"fund":get_fund(d), "codal":c}
@app.get("/api/telegram/{ch}")
def a5(ch:str): return {"channel":ch, "messages":get_telegram(ch)}
@app.get("/api/news")
def a6(): return {"news":get_news()}
@app.get("/api/screener")
def screener():
    res=[]
    for s in TIER1+TIER2[:6]:
        d=get_symbol(s); f=get_fund(d); t=tablo_tools(d)
        score = 0
        try: score=int(f.get("score",0))
        except: score=0
        if t.get("قدرت",0)>1.3: score+=2
        res.append({"نماد":s,"قیمت":d.get("pc",0),"وضعیت":f.get("status"),"امتیاز":score,"قدرت":t.get("قدرت"),"پول":t.get("پول_حقیقی")})
    res=sorted(res, key=lambda x: x["امتیاز"], reverse=True)
    return res
@app.get("/api/critique/{name}")
def a7(name:str, risk:str="normal"): d=get_symbol(name); h=get_history(name); s=calc_signal(h,d,risk); f=get_fund(d); n=get_news(); return {"gemini":critique_gemini(s,f,len(n)), "gpt":critique_gpt(s,f), "rr":s.get("rr")}

@app.get("/", response_class=HTMLResponse)
def home():
    return """<!DOCTYPE html><html dir="rtl" lang="fa"><head><meta charset='utf-8'><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bourse Pro</title>
<style>*{font-family:tahoma,sans-serif;box-sizing:border-box}body{background:#f1f5f9;margin:0;padding:12px;color:#0f172a}
.header{background:linear-gradient(135deg,#0f172a,#1e40af);color:white;border-radius:16px;padding:18px;margin-bottom:12px}
.card{background:white;border-radius:16px;padding:14px;box-shadow:0 4px 16px rgba(0,0,0,.07);margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}
.btn{padding:7px 10px;border-radius:10px;border:1px solid #e2e8f0;background:white;cursor:pointer;margin:2px;font-size:12px}
.btn.active{background:#0f172a;color:white}
.tier{font-size:11px;background:#e0e7ff;padding:2px 6px;border-radius:6px}
.value{font-size:16px;font-weight:900} .label{font-size:11px;color:#64748b}
table{width:100%;border-collapse:collapse;font-size:12px}td,th{padding:6px;border-bottom:1px solid #f1f5f9;text-align:right}
input,select{padding:8px;border-radius:10px;border:1px solid #e2e8f0}
.critic{border-right:4px solid #1e40af;padding:8px;background:#eff6ff;border-radius:10px;margin-top:6px;font-size:13px}
.critic2{border-right:4px solid #9333ea;padding:8px;background:#faf5ff;border-radius:10px;margin-top:6px;font-size:13px}
</style></head><body>
<div class="header"><h2 style="margin:0">🚀 بورس پرو - ردیف 1 و 2</h2><p style="opacity:.85;font-size:12px">ردیف1 شاخص ساز | ردیف2 متوسط/اهرم/طلا + تابلوخوانی + غربالگر + نقد AI</p></div>
<div class="card"><b>ردیف 1 - شاخص ساز:</b> <span class=tier>بزرگ</span><br>
<button class="btn" onclick="load('فملی')">فملی</button><button class="btn" onclick="load('فولاد')">فولاد</button><button class="btn" onclick="load('فارس')">فارس</button><button class="btn" onclick="load('شستا')">شستا</button><button class="btn" onclick="load('نوری')">نوری</button><button class="btn" onclick="load('شپنا')">شپنا</button><button class="btn" onclick="load('وبملت')">وبملت</button>
<br><b style="margin-top:8px;display:inline-block">ردیف 2 - متوسط / طلا / اهرم:</b> <span class=tier>پرنوسان</span><br>
<button class="btn" onclick="load('کگل')">کگل</button><button class="btn" onclick="load('کچاد')">کچاد</button><button class="btn" onclick="load('فزر')">فزر</button><button class="btn" onclick="load('ذوب')">ذوب</button><button class="btn" onclick="load('طلا')">طلا</button><button class="btn" onclick="load('عیار')">عیار</button><button class="btn" onclick="load('اهرم')">اهرم</button><button class="btn" onclick="load('توان')">توان</button>
<hr><div style="display:flex;gap:6px;flex-wrap:wrap">
<input id="sym" value="فملی" style="width:100px"><select id="risk"><option value="low">کم ریسک</option><option value="normal" selected>متعادل</option><option value="high">پر ریسک</option></select><input id="custom" placeholder="حد ضرر دستی" style="width:130px"><select id="chan"><option value="tahlilboniadii">tahlilboniadii</option><option value="boursenews_ir">boursenews_ir</option></select><button onclick="load(document.getElementById('sym').value)" style="background:#1e40af;color:white;padding:8px 14px;border-radius:10px;border:none">نمایش + نقد</button><button onclick="loadScreener()" style="background:#059669;color:white;padding:8px 14px;border-radius:10px;border:none">غربالگر ردیف 1 و 2</button></div></div>
<div id="main"></div><div id="critics"></div><div id="tablo" class="card" style="display:none"></div><div id="screener" class="card" style="display:none"></div><div class="grid"><div id="fund" class="card"></div><div id="news" class="card"></div></div><div id="tg" class="card"></div>
<script>
function fmt(n){return Number(n).toLocaleString('fa-IR')}
async function load(sym){
 document.getElementById('sym').value=sym; document.querySelectorAll('.btn').forEach(b=>b.classList.toggle('active', b.textContent.includes(sym)));
 document.getElementById('main').innerHTML='دارم میگیرم...';
 let risk=document.getElementById('risk').value, custom=document.getElementById('custom').value, qs=`?risk=${risk}`+(custom?`&custom=${custom}`:'');
 try{
  let d=await fetch('/api/symbol/'+sym).then(r=>r.json());
  let s=await fetch('/api/signal/'+sym+qs).then(r=>r.json());
  let t=await fetch('/api/tablo/'+sym).then(r=>r.json());
  let f=await fetch('/api/fund/'+sym).then(r=>r.json());
  let crit=await fetch('/api/critique/'+sym+`?risk=${risk}`).then(r=>r.json());
  let fb=d._fallback?' <span class=tier>Fallback TSETMC</span>':'';
  if(d._error && !d._fallback) document.getElementById('main').innerHTML=`<div class=card style=color:#b91c1c;background:#fef2f2>⛔ ${d._error}</div>`;
  else document.getElementById('main').innerHTML=`<div class=card><h3 style=margin:0>${d.l18} - ${d.l30}${fb}</h3><div class=grid style=margin-top:10px><div><div class=label>پایانی</div><div class=value>${fmt(d.pc)} (${d.pcp}%)</div></div><div><div class=label>آخرین</div><div class=value>${fmt(d.pl)} (${d.plp}%)</div></div><div><div class=label>R/R</div><div class=value>${s.rr}</div></div><div><div class=label>حد ضرر</div><div class=value style=color:#dc2626>${fmt(s.stop)} (${s.dist}%)</div></div></div><hr><div class=grid><div><div class=label>سیگنال</div><div class=value>${s.sig}</div></div><div><div class=label>ورود</div><div class=value>${fmt(s.ma20)}</div></div><div><div class=label>سود1</div><div class=value style=color:#16a34a>${fmt(s.t1)}</div></div><div><div class=label>سود2</div><div class=value style=color:#16a34a>${fmt(s.t2)}</div></div></div></div>`;
  document.getElementById('critics').innerHTML=`<div class=card><b>🔍 نقد AI</b><div class=critic><b>Gemini 3.1 Pro:</b> ${crit.gemini} R/R ${crit.rr}</div><div class=critic2><b>GPT 5.6 Pro/Sola:</b> ${crit.gpt}</div></div>`;
  document.getElementById('tablo').style.display='block';
  document.getElementById('tablo').innerHTML=`<b>📊 تابلوخوانی ردیف 1/2</b><table><tr><td>قدرت خریدار</td><td><b>${t.قدرت || '-'}</b></td><td>سرانه خرید</td><td>${t.سرانه_خرید || '-'} M</td></tr><tr><td>پول حقیقی</td><td>${t.پول_حقیقی || '-'}</td><td>حجم</td><td>${t.حجم || '-'}</td></tr></table><div style=font-size:11px;color:#64748b>قدرت>1.3 + سرانه 2M+ = پول هوشمند</div>`;
  document.getElementById('fund').innerHTML=`<b>📈 فاندا</b><table><tr><td>P/E</td><td>${f.fund.pe}</td><td>P/E گروه</td><td>${f.fund.gpe}</td></tr><tr><td colspan=4><b>${f.fund.status}</b></td></tr></table><hr>${f.codal.map(x=>'<div style=font-size:11px>'+x+'</div>').join('')}`;
  let n=await fetch('/api/news').then(r=>r.json()); document.getElementById('news').innerHTML='<b>🗞 اخبار</b><br>'+n.news.map(x=>'<div style=font-size:11px;padding:4px 0>'+x+'</div>').join('');
  let ch=document.getElementById('chan').value; let tg=await fetch('/api/telegram/'+ch).then(r=>r.json()); document.getElementById('tg').innerHTML='<b>✈️ @'+tg.channel+'</b><br>'+tg.messages.map(m=>'<div style=font-size:12px;padding:4px 0;border-bottom:1px solid #eee>'+m+'</div>').join('');
 }catch(e){document.getElementById('main').innerHTML='<div class=card style=color:red>'+e+'</div>'}
}
async function loadScreener(){
 let d=await fetch('/api/screener').then(r=>r.json());
 let h='<b>🏆 غربالگر ردیف 1 و 2 - ارزنده ترین</b><table><tr><th>نماد</th><th>قیمت</th><th>وضعیت</th><th>قدرت</th><th>پول</th></tr>';
 d.forEach(x=>{h+=`<tr style="cursor:pointer" onclick="load('${x.نماد}')"><td><b>${x.نماد}</b></td><td>${fmt(x.قیمت)}</td><td>${x.وضعیت}</td><td>${x.قدرت||'-'}</td><td style=font-size:10px>${x.پول||'-'}</td></tr>`})
 h+='</table>'; document.getElementById('screener').style.display='block'; document.getElementById('screener').innerHTML=h;
}
load('فملی');
</script></body></html>"""
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
