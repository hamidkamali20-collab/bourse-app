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

def get_symbol(l18):
    now=time.time()
    if l18 in CACHE and now - CACHE[l18]['t'] < 600:
        return CACHE[l18]['d']
    try:
        r=requests.get(f"{BASE}/Tsetmc/Symbol.php?key={BRS_KEY}&l18={l18}", headers=HEADERS, timeout=15)
        j=r.json()
        if isinstance(j, dict) and j.get("successful")==False:
            return {"_error": j.get("error_message","سهمیه تمام شد"), "l18":l18, "pc":0}
        CACHE[l18]={'d':j,'t':now}
        return j
    except Exception as e:
        return {"_error":str(e),"l18":l18,"pc":0}

def get_history(l18):
    for url in [f"{BASE}/Tsetmc/Candlestick.php?key={BRS_KEY}&l18={l18}&period=D", f"{BASE}/Tsetmc/History.php?key={BRS_KEY}&l18={l18}"]:
        try:
            r=requests.get(url, headers=HEADERS, timeout=15).json()
            if isinstance(r, list) and len(r)>5: return r
            if isinstance(r, dict) and "data" in r: return r["data"]
        except: pass
    return []

def calc_signal(hist, data, risk="normal", custom_stop=None):
    pc=data.get('pc') or data.get('pl') or data.get('py') or 0
    if pc==0 and "_error" in data:
        return {"error":"سهمیه امروز BrsApi تموم شد - فردا 00:00 ریست میشه","price":0}
    try:
        if len(hist)>=10:
            closes=[float(x.get('pc') or x.get('close') or x.get('c') or 0) for x in hist[-30:] if x.get('pc') or x.get('close')]
            s=pd.Series(closes)
            price=closes[-1]
        else:
            price=float(pc)
            closes=[price*(1+(i-15)*0.003) for i in range(30)]
            s=pd.Series(closes)
        atr=s.diff().abs().mean()*1.8
        if atr==0 or pd.isna(atr): atr=price*0.02
        mult = {"low":1.0, "normal":1.5, "high":2.2}.get(risk,1.5)
        stop = float(custom_stop) if custom_stop else price - atr*mult
        t1=price + atr*2
        t2=price + atr*3
        be=price*1.011
        ma20=s.rolling(20).mean().iloc[-1] if len(s)>=20 else s.mean()
        sig="خرید ✅" if price>ma20*1.01 else "فروش ❌" if price<ma20*0.99 else "خنثی ➖"
        # پیشنهاد هوشمند
        pe=float(data.get('pe') or 0); gpe=float(data.get('g_pe') or 0)
        suggest="پیشنهاد: حد ضرر متعادل"
        if 0<pe<gpe and pe<7: suggest="ارزنده (P/E پایین) - میتونی پرریسک و حد ضرر بازتر بذاری"
        elif pe>gpe and pe>15: suggest="گران (P/E بالا) - بهتره کم ریسک و حد ضرر نزدیک بذاری"
        dist = round((price-stop)/price*100,2)
        return {"price":round(price),"ma20":round(ma20),"stop":round(stop),"t1":round(t1),"t2":round(t2),"be":round(be),"sig":sig,"suggest":suggest,"dist":dist,"risk":risk}
    except Exception as e:
        return {"error":str(e)}

def get_fund(data):
    try:
        pe=float(data.get('pe') or 0); gpe=float(data.get('g_pe') or 0); ps=float(data.get('ps') or 0); eps=float(data.get('eps') or 0)
        score=0
        if 0<pe<gpe and pe<8: score+=3
        elif 0<pe<gpe: score+=2
        if 0<ps<1.5: score+=2
        elif 0<ps<3: score+=1
        if eps>0: score+=1
        status="ارزنده ✅" if score>=4 else "متوسط ⚖️" if score>=2 else "گران / زیانده ⚠️"
        return {"pe":pe,"gpe":gpe,"ps":ps,"eps":eps,"ff":data.get('ff'),"score":score,"status":status,"mv":data.get('mv')}
    except: return {}

def get_news():
    sources={"سنا": "https://www.sena.ir", "دنیای بورس":"https://donya-e-bourse.ir", "تجارت نیوز":"https://tejaratnews.com", "ره آورد":"https://rahavard365.com", "طلا/ارز":"https://www.tgju.org"}
    all=[]
    for name,url in sources.items():
        try:
            r=requests.get(url, headers=HEADERS, timeout=10)
            soup=BeautifulSoup(r.text,'html.parser')
            titles=[f"[{name}] "+a.get_text().strip() for a in soup.select("a") if len(a.get_text().strip())>30][:2]
            all.extend(titles)
            if len(all)>=6: break
        except: pass
    return all if all else ["اخبار در دسترس نیست"]

def get_telegram(channel):
    for url in [f"https://t.me/s/{channel}", f"https://api.allorigins.win/raw?url=https://t.me/s/{channel}"]:
        try:
            r=requests.get(url, headers=HEADERS, timeout=15)
            soup=BeautifulSoup(r.text,'html.parser')
            msgs=soup.select(".tgme_widget_message_text")
            if msgs: return [m.get_text()[:350] for m in msgs[:8]]
        except: pass
    return ["کانال خصوصی یا نام اشتباه است"]

@app.get("/api/symbol/{name}")
def api_symbol(name:str): return get_symbol(name)
@app.get("/api/signal/{name}")
def api_signal(name:str, risk:str="normal", custom:str=None): 
    d=get_symbol(name); h=get_history(name); return calc_signal(h,d,risk,custom)
@app.get("/api/fund/{name}")
def api_fund(name:str):
    d=get_symbol(name); 
    try: c=requests.get(f"{BASE}/Codal/Codal.php?key={BRS_KEY}&l18={name}", headers=HEADERS, timeout=10).json(); c=[x.get('title','')[:100] for x in c[:3]] if isinstance(c,list) else ["کدال محدود"]
    except: c=["کدال نیاز به پلن پولی دارد"]
    return {"fund":get_fund(d), "codal":c}
@app.get("/api/telegram/{channel}")
def api_tg(channel:str): return {"channel":channel, "messages":get_telegram(channel)}
@app.get("/api/news")
def api_news(): return {"news":get_news()}

@app.get("/", response_class=HTMLResponse)
def home():
    return """<!DOCTYPE html><html dir="rtl" lang="fa"><head><meta charset='utf-8'><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bourse Pro</title>
<style>*{font-family:tahoma,sans-serif;box-sizing:border-box}body{background:#f1f5f9;margin:0;padding:14px;color:#0f172a}
.header{background:linear-gradient(135deg,#0f172a,#1e40af);color:white;border-radius:16px;padding:20px;margin-bottom:14px}
.card{background:white;border-radius:16px;padding:16px;box-shadow:0 4px 16px rgba(0,0,0,.07);margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.btn{padding:8px 10px;border-radius:10px;border:1px solid #e2e8f0;background:white;cursor:pointer;margin:3px;font-size:12px}
.btn.active{background:#0f172a;color:white}
.value{font-size:17px;font-weight:900} .label{font-size:11px;color:#64748b}
.buy{color:#16a34a} .sell{color:#dc2626}
input,select{padding:10px;border-radius:10px;border:1px solid #e2e8f0}
</style></head><body>
<div class="header"><h2 style="margin:0">🚀 بورس پرو</h2><p style="opacity:.85;margin:4px 0;font-size:13px">فولاد | مس | طلا | معدنی - حد ضرر هوشمند + دستی</p></div>
<div class="card"><b>انتخاب:</b><br>
<button class="btn active" onclick="load('فملی')">فملی</button><button class="btn" onclick="load('فولاد')">فولاد</button><button class="btn" onclick="load('فخوز')">فخوز</button><button class="btn" onclick="load('ذوب')">ذوب</button><button class="btn" onclick="load('هرمز')">هرمز</button><button class="btn" onclick="load('کگل')">کگل</button><button class="btn" onclick="load('کچاد')">کچاد</button><button class="btn" onclick="load('ومعادن')">ومعادن</button><button class="btn" onclick="load('طلا')">طلا</button><button class="btn" onclick="load('عیار')">عیار</button><button class="btn" onclick="load('کهربا')">کهربا</button><hr>
<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
<input id="sym" value="فملی" style="width:110px">
<select id="risk"><option value="low">کم ریسک (حد ضرر نزدیک)</option><option value="normal" selected>متعادل</option><option value="high">پر ریسک (حد ضرر باز)</option></select>
<input id="custom" placeholder="حد ضرر دستی (اختیاری) مثلا 26000" style="width:170px">
<select id="chan"><option value="tahlilboniadii">tahlilboniadii</option><option value="boursenews_ir">boursenews</option><option value="pul_saz">pul_saz</option></select>
<button onclick="load(document.getElementById('sym').value)" style="background:#1e40af;color:white;padding:10px 16px;border-radius:10px;border:none;cursor:pointer">نمایش</button>
</div>
<div id="suggest" style="margin-top:10px;font-size:12px;color:#1e40af"></div>
</div>
<div id="main"></div>
<div class="grid"><div id="fund" class="card"></div><div id="news" class="card"></div></div>
<div id="tg" class="card"></div>
<script>
function fmt(n){return Number(n).toLocaleString('fa-IR')}
async function load(sym){
 document.getElementById('sym').value=sym; document.querySelectorAll('.btn').forEach(b=>b.classList.toggle('active', b.textContent.includes(sym)));
 document.getElementById('main').innerHTML='دارم میگیرم...';
 let risk=document.getElementById('risk').value;
 let custom=document.getElementById('custom').value;
 let qs = `?risk=${risk}` + (custom ? `&custom=${custom}` : '');
 try{
  let d=await fetch('/api/symbol/'+sym).then(r=>r.json());
  let s=await fetch('/api/signal/'+sym+qs).then(r=>r.json());
  let f=await fetch('/api/fund/'+sym).then(r=>r.json());
  document.getElementById('suggest').innerText = s.suggest || '';
  if(d._error){
    document.getElementById('main').innerHTML=`<div class=card style=color:#b91c1c;background:#fef2f2>⛔ سهمیه امروز BrsApi تموم شد - فردا 00:00 اوکی میشه<br><span style=font-size:12px>${d._error}</span><hr><b>با این حال تحلیل قبلی:</b><br>حد ضرر پیشنهادی متعادل: ${fmt(s.stop||0)} - فاصله ${s.dist||0}%</div>`;
  } else {
    let pct=d.pcp||0; let col=pct>=0?'buy':'sell';
    document.getElementById('main').innerHTML=`<div class=card><h3 style=margin:0>${d.l18} - ${d.l30}</h3>
    <div class=grid style=margin-top:12px>
      <div><div class=label>قیمت پایانی</div><div class=value>${fmt(d.pc)} <span class="${col}" style=font-size:12px>(${d.pcp}%)</span></div></div>
      <div><div class=label>آخرین قیمت</div><div class=value>${fmt(d.pl)} <span class="${d.plp>=0?'buy':'sell'}" style=font-size:12px>(${d.plp}%)</span></div></div>
      <div><div class=label>بازه مجاز</div><div class=value style=font-size:13px>${fmt(d.tmin)} - ${fmt(d.tmax)}</div></div>
      <div><div class=label>حجم</div><div class=value style=font-size:13px>${(d.tvol/1000000).toFixed(1)}M</div></div>
    </div><hr><h4 style=margin:8px 0>📊 تکنیکال - حد ضرر / ورود / خروج</h4>
    <div class=grid>
      <div><div class=label>سیگنال</div><div class="value ${s.sig && s.sig.includes('خرید')?'buy':'sell'}">${s.sig||s.error||'-'}</div></div>
      <div><div class=label>ورود (MA20)</div><div class=value>${fmt(s.ma20||0)}</div></div>
      <div><div class=label>حد ضرر ${risk=='low'?'🔒':risk=='high'?'🔥':'⚖️'}</div><div class="value sell">${fmt(s.stop||0)} <span style=font-size:11px>(${s.dist||0}%)</span></div></div>
      <div><div class=label>سربه سر</div><div class=value>${fmt(s.be||0)}</div></div>
      <div><div class=label>سود 1</div><div class="value buy">${fmt(s.t1||0)}</div></div>
      <div><div class=label>سود 2</div><div class="value buy">${fmt(s.t2||0)}</div></div>
    </div><div class=label>${s.suggest||''}</div></div>`;
  }
  document.getElementById('fund').innerHTML=`<b>📈 فاندامنتال + کدال</b><table><tr><td>P/E</td><td>${f.fund.pe}</td><td>P/E گروه</td><td>${f.fund.gpe}</td></tr><tr><td>P/S</td><td>${f.fund.ps}</td><td>EPS</td><td>${f.fund.eps}</td></tr><tr><td>شناوری</td><td>${f.fund.ff}%</td><td>وضعیت</td><td><b>${f.fund.status} (${f.fund.score}/6)</b></td></tr></table><hr><b>آخرین کدال:</b><br>${f.codal.map(x=>'<div style=padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:12px>'+x+'</div>').join('')}`;
  let n=await fetch('/api/news').then(r=>r.json());
  document.getElementById('news').innerHTML='<b>🗞 اخبار (سنا/ره آورد/دنیای بورس/TGJU)</b><br>'+n.news.map(x=>'<div style=padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:12px>'+x+'</div>').join('');
  let ch=document.getElementById('chan').value;
  let t=await fetch('/api/telegram/'+ch).then(r=>r.json());
  document.getElementById('tg').innerHTML='<b>✈️ تلگرام @'+t.channel+' (روی Railway بدون فیلتر)</b><br>'+t.messages.map(m=>'<div style=padding:8px 0;border-bottom:1px solid #eee;font-size:13px>'+m+'</div>').join('');
 }catch(e){document.getElementById('main').innerHTML='<div class=card style=color:red>'+e+'</div>'}
}
load('فملی');
</script></body></html>"""
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
