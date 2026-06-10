import json, random

random.seed(11)
def rid(): return ''.join(random.choice('abcdefghijklmnopqrstuvwxyz0123456789') for _ in range(16))
def nonce(): return random.randint(1, 2**31)
def base(extra):
    e={"angle":0,"strokeColor":"#1e1e1e","backgroundColor":"transparent","fillStyle":"solid",
       "strokeWidth":2,"strokeStyle":"solid","roughness":0,"opacity":100,"groupIds":[],"frameId":None,
       "roundness":{"type":3},"seed":nonce(),"version":1,"versionNonce":nonce(),"isDeleted":False,
       "boundElements":[],"updated":1717200000000,"link":None,"locked":False}
    e.update(extra); return e

CENTER=900; GAP=40; ROW_GAP=46; HEADER=50; STAGE_GAP=92

# stage = (key,title,stroke,bg, rows=[[(key,label,w,h,kind)]])  kind: r=rounded, s=store
STAGES=[
 ("sA","A · SOURCES   —   you keep adding","#1971c2","#e7f5ff",[
   [("registry","SOURCES REGISTRY / WATCHLIST\nchannels · playlists · video URLs\n(add anytime — the brain grows)",520,84,"s")],
 ]),
 ("sB","B · CONTINUOUS INGESTION   (residential IP / proxy · incremental)","#0ca678","#e6fcf5",[
   [("scheduler","Scheduler / Jobs   —   periodic re-check · new videos only",520,52,"r")],
   [("resolver","URL Resolver   —   video vs channel / playlist   (yt-dlp --flat-playlist)",560,52,"r")],
   [("trans","Transcripts\nyt-transcript-api\n+ whisper fallback",250,84,"r"),
    ("sig","SIGNALS  (yt-dlp)\nviews · likes · dates\nduration · title",250,84,"r"),
    ("comments","Comments\ncommentThreads /\n--write-comments",250,84,"r")],
 ]),
 ("sC","C · RAW LAKE   (append-only · cached permanently)","#2f9e44","#ebfbee",[
   [("raw","RAW STORE   ·   transcripts · metadata · signals · comments",560,56,"s")],
 ]),
 ("sD","D · PROCESSING & ENRICHMENT   (re-runs on every new batch → self-updating)","#37b24d","#ebfbee",[
   [("chunk","Chunk transcripts\n~500 tok · timestamps",250,72,"r"),
    ("baselines","Channel baselines\nmedian views\n(outlier denominator)",250,72,"r"),
    ("embed","Embeddings\n→ vector index\n(Qdrant / pgvector)",250,72,"r")],
 ]),
 ("sE","E · THE BRAIN    ★  reusable knowledge · insights · virality model","#e03131","#fff5f5",[
   [("outlier","Outlier scoring\nviews ÷ median\nPROVEN demand",210,90,"r"),
    ("pattern","Pattern mining\nwinning formats\n(LLM)",210,90,"r"),
    ("cmine","Comment mining\naudience pain-points\n(LLM)",210,90,"r"),
    ("gapdem","Content-gap +\ndemand validation",210,90,"r"),
    ("style","Style-cards\ntone · hooks · pacing\n(LLM)",210,90,"r")],
   [("brain","BRAIN STORE   ·   proven topics · winning formats · audience questions · gaps · style-cards · vector embeddings",1000,60,"s")],
   [("virality","★  VIRALITY MODEL + BACKTESTER   ·   features (title/format/topic/demand) → predict outlier multiplier   ·   time-split backtest:  ROC-AUC · precision@k · correlation",1000,64,"s")],
 ]),
 ("sF","F · BRAIN API / SDK   —   the contract (other tools = separate future repos)","#7048e8","#f3f0ff",[
   [("api","REST + typed SDK · auth\nquery insights · semantic search (RAG) · get style-card · validate demand · score virality · backtest report · rank ideas",820,84,"s")],
 ]),
 ("sG","G · YOUTUBE SCRIPT WRITER   (the only consumer in this repo)","#e8590c","#fff4e6",[
   [("ideas","Evidence-ranked ideas   —   proven demand · gap · style fit",520,52,"r")],
   [("vgate","★  VIRALITY BACKTEST GATE   —   predicted multiplier vs proven outliers · keep only high-scorers",640,56,"r")],
   [("outline","Outline → section-wise expand → polish   (Hook · Setup · Body×3-4 · CTA)",560,52,"r")],
   [("scriptout","Ranked ideas + why (evidence + predicted virality)   ·   full script (markdown)   ·   regenerate",640,52,"r")],
 ]),
]

STORE_FILL={"sA":"#d0ebff","sC":"#b2f2bb","sE":"#ffe3e3","sF":"#e5dbff"}

nodes={}; frames=[]; y=92
for skey,title,fs,fbg,rows in STAGES:
    stop=y; y+=HEADER; minx=1e9; maxx=-1e9
    for row in rows:
        rh=max(h for *_,h,_ in row)
        tot=sum(w for _,_,w,_,_ in row)+GAP*(len(row)-1); x=CENTER-tot/2
        for key,label,w,h,kind in row:
            fill=STORE_FILL.get(skey,"#e9ecef") if kind=="s" else "#ffffff"
            nodes[key]=dict(id=rid(),tid=rid(),x=x,y=y,w=w,h=h,label=label,kind=kind,fill=fill,stage=skey)
            minx=min(minx,x); maxx=max(maxx,x+w); x+=w+GAP
        y+=rh+ROW_GAP
    frames.append((skey,title,fs,fbg,minx-34,stop,(maxx-minx)+68,(y-ROW_GAP)-stop+30))
    y+=STAGE_GAP

stage_node_minx=min(n["x"] for n in nodes.values())
stage_node_maxx=max(n["x"]+n["w"] for n in nodes.values())

# ---- side node: MARKET DEMAND (external, free) — feeds content-gap producer ----
gp=nodes["gapdem"]
nodes["market"]=dict(id=rid(),tid=rid(),x=gp["x"]+gp["w"]+90,y=gp["y"]-2,w=250,h=92,
                     label="MARKET DEMAND  (free)\nGoogle Trends (pytrends)\n+ search-suggest",
                     kind="r",fill="#c5f6fa",stage="ext")

# ---- side node: CLAUDE (subscription) reasoning engine — tall, left of the spine ----
top=nodes["chunk"]["y"]-18
bot=nodes["scriptout"]["y"]+nodes["scriptout"]["h"]
nodes["claude"]=dict(id=rid(),tid=rid(),x=stage_node_minx-250,y=top,w=200,h=bot-top,
                     label="CLAUDE\n(subscription)\n\nreasoning\nengine\n\npattern ·\ncomment ·\nstyle mining\n+ idea / script\ngeneration\n\n(pluggable\nLLM provider)",
                     kind="r",fill="#ffec99",stage="ext")

elements=[]
# spine frames
for skey,title,fs,fbg,fx,fy,fw,fh in frames:
    elements.append(base({"id":rid(),"type":"rectangle","x":fx,"y":fy,"width":fw,"height":fh,
        "strokeColor":fs,"backgroundColor":fbg,"strokeWidth":(3 if skey=="sE" else 2),
        "roundness":{"type":3},"opacity":50}))
    elements.append(base({"id":rid(),"type":"text","x":fx+18,"y":fy+13,"width":fw-36,"height":28,
        "strokeColor":fs,"roundness":None,"text":title,"fontSize":21,"fontFamily":1,"textAlign":"left",
        "verticalAlign":"top","baseline":19,"containerId":None,"originalText":title,"lineHeight":1.25}))

# market mini-frame ("external")
mk=nodes["market"]
elements.append(base({"id":rid(),"type":"rectangle","x":mk["x"]-22,"y":mk["y"]-46,"width":mk["w"]+44,
    "height":mk["h"]+66,"strokeColor":"#0c8599","backgroundColor":"#e3fafc","strokeWidth":2,
    "roundness":{"type":3},"opacity":45}))
elements.append(base({"id":rid(),"type":"text","x":mk["x"]-14,"y":mk["y"]-40,"width":mk["w"]+30,
    "height":24,"strokeColor":"#0c8599","roundness":None,"text":"external","fontSize":18,
    "fontFamily":1,"textAlign":"left","verticalAlign":"top","baseline":16,"containerId":None,
    "originalText":"external","lineHeight":1.25}))

# edges: (from,to,style)  style: ''=solid  'd'=dashed  'spine'=thick
E=[("registry","scheduler","spine"),
   ("scheduler","resolver","spine"),
   ("resolver","trans",""),("resolver","sig",""),("resolver","comments",""),
   ("trans","raw",""),("sig","raw",""),("comments","raw",""),
   ("raw","chunk",""),("raw","baselines","spine"),("raw","embed",""),
   ("baselines","outlier",""),("chunk","pattern",""),("chunk","cmine",""),
   ("chunk","style",""),("embed","brain","spine"),
   ("market","gapdem",""),
   ("outlier","brain",""),("pattern","brain",""),("cmine","brain",""),
   ("gapdem","brain",""),("style","brain",""),
   ("brain","virality","spine"),
   ("virality","api","spine"),
   ("api","ideas","spine"),
   ("ideas","vgate","spine"),
   ("vgate","outline","spine"),
   ("outline","scriptout","spine"),
   # the backtested virality model powers the generation gate
   ("virality","vgate","d"),
   # Claude reasoning engine (dashed) into the LLM-powered mining + generation steps
   ("claude","pattern","d"),("claude","cmine","d"),("claude","style","d"),
   ("claude","ideas","d"),("claude","outline","d")]

def cen(n): return (n["x"]+n["w"]/2,n["y"]+n["h"]/2)
def pts(a,b):
    ax,ay=cen(a); bx,by=cen(b); dx,dy=bx-ax,by-ay
    if abs(dy)>=abs(dx):
        return (ax,a["y"]+a["h"],bx,b["y"]) if dy>0 else (ax,a["y"],bx,b["y"]+b["h"])
    return (a["x"]+a["w"],ay,b["x"],by) if dx>0 else (a["x"],ay,b["x"]+b["w"],by)
abind={}
def arrow(aid,sx,sy,pointlist,color,dashed,bindA=None,bindB=None):
    el=base({"id":aid,"type":"arrow","x":sx,"y":sy,
        "width":max(abs(p[0]) for p in pointlist),"height":max(abs(p[1]) for p in pointlist),
        "points":pointlist,"strokeColor":color,"strokeStyle":"dashed" if dashed else "solid",
        "strokeWidth":2.5 if not dashed and color=="#343a40" else 2,"roughness":0,
        "roundness":{"type":2},"startArrowhead":None,"endArrowhead":"arrow"})
    if bindA: el["startBinding"]={"elementId":bindA,"focus":0,"gap":6}
    if bindB: el["endBinding"]={"elementId":bindB,"focus":0,"gap":6}
    elements.append(el)
for frm,to,style in E:
    a,b=nodes[frm],nodes[to]; sx,sy,ex,ey=pts(a,b); aid=rid()
    color="#343a40" if style=="spine" else "#9775fa" if (style=="d" and frm=="claude") else "#868e96" if style=="d" else "#495057"
    arrow(aid,sx,sy,[[0,0],[ex-sx,ey-sy]],color,style=="d",a["id"],b["id"])
    abind.setdefault(a["id"],[]).append(aid); abind.setdefault(b["id"],[]).append(aid)

# self-update loop: brain -> scheduler, routed on the far-right margin (elbow)
br=nodes["brain"]; sc=nodes["scheduler"]
RM=max(stage_node_maxx, mk["x"]+mk["w"])+70
aid=rid(); sx,sy=br["x"]+br["w"],br["y"]+br["h"]/2
scy=sc["y"]+sc["h"]/2; scx=sc["x"]+sc["w"]
arrow(aid,sx,sy,[[0,0],[RM-sx,0],[RM-sx,scy-sy],[scx-sx,scy-sy]],"#f76707",True)
lt=base({"id":rid(),"type":"text","x":RM+8,"y":(sy+scy)/2-22,"width":150,"height":44,
    "strokeColor":"#f76707","backgroundColor":"#ffffff","roundness":None,
    "text":"continuous\nself-update /\nre-index","fontSize":13,"fontFamily":1,"textAlign":"left",
    "verticalAlign":"middle","baseline":11,"containerId":None,
    "originalText":"continuous\nself-update /\nre-index","lineHeight":1.25})
elements.append(lt)

# performance-feedback (future): published script -> virality model, dashed on the right-inner margin
aid=rid(); ax=nodes["scriptout"]; vm=nodes["virality"]
sx,sy=ax["x"]+ax["w"],ax["y"]+ax["h"]/2
FM=RM-44; vy=vm["y"]+vm["h"]/2; vx=vm["x"]+vm["w"]
arrow(aid,sx,sy,[[0,0],[FM-sx,0],[FM-sx,vy-sy],[vx-sx,vy-sy]],"#ced4da",True)
elements.append(base({"id":rid(),"type":"text","x":FM-160,"y":sy-26,"width":156,"height":32,
    "strokeColor":"#adb5bd","backgroundColor":"#ffffff","roundness":None,
    "text":"performance feedback\n→ re-train (future)","fontSize":12,"fontFamily":1,"textAlign":"right",
    "verticalAlign":"top","baseline":10,"containerId":None,
    "originalText":"performance feedback\n→ re-train (future)","lineHeight":1.25}))

# nodes
for key,n in nodes.items():
    lines=n["label"].count("\n")+1
    emph=key in ("virality","vgate")  # virality model + gate get a red emphasis border
    elements.append(base({"id":n["id"],"type":"rectangle","x":n["x"],"y":n["y"],"width":n["w"],
        "height":n["h"],"strokeColor":"#e03131" if emph else "#1e1e1e",
        "backgroundColor":n["fill"],"strokeWidth":3 if emph else 2,
        "roundness":{"type":3} if n["kind"]=="r" else None,
        "boundElements":[{"type":"text","id":n["tid"]}]+[{"type":"arrow","id":x} for x in abind.get(n["id"],[])]}))
    fsz=15 if key not in ("claude",) else 14
    elements.append(base({"id":n["tid"],"type":"text","x":n["x"]+6,
        "y":n["y"]+n["h"]/2-(lines*fsz*1.25)/2,"width":n["w"]-12,"height":lines*fsz*1.25,
        "strokeColor":"#1e1e1e","roundness":None,"text":n["label"],"fontSize":fsz,"fontFamily":1,
        "textAlign":"center","verticalAlign":"middle","baseline":12,"containerId":n["id"],
        "originalText":n["label"],"lineHeight":1.25}))

# title + subtitle
title="The Brain OS — self-updating YouTube knowledge engine + a backtested-for-virality script writer"
elements.append(base({"id":rid(),"type":"text","x":CENTER-490,"y":22,"width":980,"height":34,
    "strokeColor":"#1e1e1e","roundness":None,"text":title,"fontSize":24,"fontFamily":1,
    "textAlign":"center","verticalAlign":"top","baseline":21,"containerId":None,
    "originalText":title,"lineHeight":1.25}))
sub="scrape what you add  →  analyze what performs  →  BACKTEST ideas for virality  →  write YouTube scripts in a proven style"
elements.append(base({"id":rid(),"type":"text","x":CENTER-490,"y":56,"width":980,"height":22,
    "strokeColor":"#868e96","roundness":None,"text":sub,"fontSize":15,"fontFamily":1,
    "textAlign":"center","verticalAlign":"top","baseline":13,"containerId":None,
    "originalText":sub,"lineHeight":1.25}))

doc={"type":"excalidraw","version":2,"source":"https://excalidraw.com","elements":elements,
     "appState":{"gridSize":None,"viewBackgroundColor":"#ffffff"},"files":{}}
with open(r"C:\Genflows\Yt script writer\architecture.excalidraw","w",encoding="utf-8") as f:
    json.dump(doc,f,indent=2,ensure_ascii=False)
print("elements:",len(elements),"nodes:",len(nodes),"edges:",len(E)+2)
