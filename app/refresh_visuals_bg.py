import json
import os
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path('/opt/j3g-youtube-ai')
JOBS = ROOT / 'data/jobs'
job = sorted((p for p in JOBS.iterdir() if p.is_dir() and (p/'narration_xtts.wav').is_file()))[-1]
slides = job/'slides_v3'
slides.mkdir(exist_ok=True)
audio = job/'narration_xtts.wav'
fontpath = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
boldpath = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
W,H=720,1280
BG_OPACITY = 22  # approx 8.6%


def fit(draw, text, rect, maximum=44, minimum=18, bold=False, color='#f8fafc', spacing=10):
    x,y,w,h=rect
    path=boldpath if bold else fontpath
    for size in range(maximum,minimum-1,-1):
        font=ImageFont.truetype(path,size)
        lines=[]
        for paragraph in text.split('\n'):
            if not paragraph.strip():
                lines.append('')
                continue
            line=''
            for word in paragraph.split():
                candidate=(line+' '+word).strip()
                if draw.textbbox((0,0),candidate,font=font)[2] <= w:
                    line=candidate
                else:
                    if line:
                        lines.append(line)
                    line=word
            if line:
                lines.append(line)
        block='\n'.join(lines)
        bounds=draw.multiline_textbbox((0,0),block,font=font,spacing=spacing,align='center')
        tw,th=bounds[2]-bounds[0],bounds[3]-bounds[1]
        if tw<=w and th<=h:
            tx=x+(w-tw)/2-bounds[0]
            ty=y+(h-th)/2-bounds[1]
            draw.multiline_text((tx,ty),block,font=font,fill=color,spacing=spacing,align='center')
            return size
    raise ValueError(f'Text cannot fit within {rect}: {text[:75]}')


def panel(d,xy,fill='#17263b',border='#3b82f6',radius=26):
    d.rounded_rectangle(xy,radius=radius,fill=fill,outline=border,width=3)


def soft_bg_base(color='#0b1221'):
    return Image.new('RGBA',(W,H),color)


def tech_grid(draw, color=(130,180,220,BG_OPACITY)):
    for x in range(0,W,60):
        draw.line((x,0,x,H),fill=color,width=1)
    for y in range(0,H,60):
        draw.line((0,y,W,y),fill=color,width=1)


def bg_building_network():
    bg=soft_bg_base()
    d=ImageDraw.Draw(bg)
    tech_grid(d,(120,170,210,10))
    # skyline
    rects=[(45,760,150,1120),(160,650,270,1120),(285,710,385,1120),(405,600,520,1120),(540,690,660,1120)]
    for r in rects:
        d.rounded_rectangle(r,radius=8,fill=(160,200,255,BG_OPACITY))
        for wx in range(r[0]+14,r[2]-16,22):
            for wy in range(r[1]+18,r[3]-18,28):
                d.rectangle((wx,wy,wx+8,wy+10),fill=(220,240,255,16))
    # connecting nodes
    nodes=[(125,320),(360,240),(580,330),(250,450),(470,470)]
    for a,b in zip(nodes,nodes[1:]):
        d.line((a[0],a[1],b[0],b[1]),fill=(90,210,255,24),width=5)
    for x,y in nodes:
        d.ellipse((x-14,y-14,x+14,y+14),fill=(100,220,255,28),outline=(180,240,255,40),width=2)
    return bg.filter(ImageFilter.GaussianBlur(1.2))


def bg_hvac_devices():
    bg=soft_bg_base()
    d=ImageDraw.Draw(bg)
    tech_grid(d,(100,180,220,10))
    # large faint devices
    # thermostat
    d.rounded_rectangle((40,180,250,440),radius=28,outline=(180,220,255,26),width=8)
    d.ellipse((95,235,195,335),outline=(180,220,255,26),width=8)
    # AHU
    d.rounded_rectangle((420,160,680,420),radius=24,outline=(180,220,255,24),width=8)
    d.line((455,250,640,250),fill=(180,220,255,20),width=8)
    d.line((455,315,640,315),fill=(180,220,255,20),width=8)
    # VAV
    d.polygon([(70,850),(200,760),(250,850),(120,940)],outline=(180,220,255,24),width=8)
    # chiller
    d.rounded_rectangle((430,780,670,980),radius=20,outline=(180,220,255,24),width=8)
    for cx in (500,600):
        d.ellipse((cx-35,825,cx+35,895),outline=(180,220,255,24),width=8)
    return bg.filter(ImageFilter.GaussianBlur(1.8))


def bg_data_diagram():
    bg=soft_bg_base()
    d=ImageDraw.Draw(bg)
    tech_grid(d,(100,180,220,10))
    boxes=[(70,180,270,300),(450,180,650,300),(260,430,460,550),(70,700,270,820),(450,700,650,820)]
    for box in boxes:
        d.rounded_rectangle(box,radius=20,outline=(170,220,255,20),width=6)
    centers=[((a+c)//2,(b+d)//2) for a,b,c,d in boxes]
    for i in range(len(centers)):
        for j in range(i+1,len(centers)):
            if abs(centers[i][0]-centers[j][0])<260 or abs(centers[i][1]-centers[j][1])<260:
                d.line((centers[i][0],centers[i][1],centers[j][0],centers[j][1]),fill=(110,220,255,18),width=4)
    for x,y in centers:
        d.ellipse((x-12,y-12,x+12,y+12),fill=(100,220,255,24))
    return bg.filter(ImageFilter.GaussianBlur(1.5))


def bg_warning_panel():
    bg=soft_bg_base('#120d12')
    d=ImageDraw.Draw(bg)
    tech_grid(d,(220,130,150,8))
    # control panel feel
    for y in range(170,1050,140):
        d.rounded_rectangle((80,y,640,y+78),radius=16,outline=(255,180,190,16),width=5)
        for x in range(100,620,70):
            d.ellipse((x,y+20,x+16,y+36),fill=(255,180,190,10))
    # warning triangle
    d.polygon([(360,260),(490,500),(230,500)],outline=(255,170,180,28),width=10)
    d.line((360,315,360,420),fill=(255,170,180,28),width=12)
    d.ellipse((352,445,368,461),fill=(255,170,180,28))
    return bg.filter(ImageFilter.GaussianBlur(1.7))


def bg_security_network():
    bg=soft_bg_base()
    d=ImageDraw.Draw(bg)
    tech_grid(d,(110,200,210,10))
    # shield
    d.polygon([(360,190),(500,250),(470,440),(360,520),(250,440),(220,250)],outline=(120,240,220,24),width=9)
    d.line((320,350,350,390),fill=(120,240,220,22),width=10)
    d.line((350,390,410,300),fill=(120,240,220,22),width=10)
    # network
    nodes=[(120,730),(220,640),(360,720),(510,640),(610,760),(220,920),(500,930)]
    edges=[(0,1),(1,2),(2,3),(3,4),(2,5),(2,6)]
    for a,b in edges:
        x1,y1=nodes[a]; x2,y2=nodes[b]
        d.line((x1,y1,x2,y2),fill=(100,220,255,18),width=5)
    for x,y in nodes:
        d.ellipse((x-16,y-16,x+16,y+16),fill=(120,220,255,22),outline=(180,240,255,28),width=2)
    return bg.filter(ImageFilter.GaussianBlur(1.4))


def compose_base(title, bgimg):
    base = Image.new('RGBA',(W,H),(11,18,33,255))
    base.alpha_composite(bgimg)
    # dark wash to keep readability
    wash = Image.new('RGBA',(W,H),(5,10,20,86))
    base.alpha_composite(wash)
    d=ImageDraw.Draw(base)
    panel(d,(34,35,686,122),fill='#123b66',border='#123b66',radius=18)
    fit(d,'J3G  TECH  EXPLAINED',(58,52,604,54),30,22,True)
    fit(d,title,(44,155,632,118),49,28,True)
    d.line((60,1150,660,1150),fill='#334155',width=2)
    fit(d,'AI EDUCATIONAL VIDEO  |  BACnet',(60,1173,600,45),23,16,False,'#b6c6db')
    return base,d

files=[]
# 1 — Overview
im,d=compose_base('WHAT IS BACnet?', bg_building_network())
d.ellipse((245,345,475,575),fill='#135a80',outline='#7dd3fc',width=5)
fit(d,'BACnet',(262,416,196,78),52,30,True)
panel(d,(65,655,655,1020))
fit(d,'Building Automation and Control Networks',(93,704,534,115),37,23,True)
fit(d,'An open standard that lets compatible building systems exchange information.',(99,854,522,128),32,21)
files.append(slides/'01_intro.png'); im.convert('RGB').save(files[-1])
# 2 — Network
im,d=compose_base('CONNECTED HVAC DEVICES', bg_hvac_devices())
coords=[(65,355,298,487),(422,355,655,487),(65,731,298,863),(422,731,655,863)]
for xy in coords:
    cx=(xy[0]+xy[2])/2;cy=(xy[1]+xy[3])/2
    d.line((360,610,cx,cy),fill='#38bdf8',width=7)
for xy,lab in zip(coords,['THERMOSTAT','AIR HANDLER','VAV BOX','CHILLER']):
    panel(d,xy,fill='#194b78',border='#7dd3fc')
    fit(d,lab,(xy[0]+14,xy[1]+20,xy[2]-xy[0]-28,xy[3]-xy[1]-40),31,19,True)
panel(d,(251,545,469,675),fill='#0b625c',border='#5eead4')
fit(d,'BACnet NETWORK',(267,555,186,110),30,20,True)
fit(d,'Compatible devices can exchange values such as temperatures, alarms, and equipment status.',(68,920,584,175),31,21)
files.append(slides/'02_devices.png'); im.convert('RGB').save(files[-1])
# 3 — Core concepts
im,d=compose_base('HOW BACnet SHARES DATA', bg_data_diagram())
concepts=[('OBJECTS','Represent information, such as an Analog Input or Schedule.'),('PROPERTIES','Describe object values, status, and other characteristics.'),('SERVICES','Allow devices to read, write, and exchange supported information.')]
for i,(heading,body) in enumerate(concepts):
    top=325+i*262
    panel(d,(65,top,655,top+220))
    fit(d,heading,(99,top+22,522,58),36,24,True,'#7dd3fc')
    fit(d,body,(102,top+92,516,103),29,20)
files.append(slides/'03_concepts.png'); im.convert('RGB').save(files[-1])
# 4 — Caution
im,d=compose_base('IMPORTANT LIMITATIONS', bg_warning_panel())
panel(d,(65,325,655,945),fill='#38202a',border='#fda4af')
fit(d,'BACnet is NOT a universal controller programming tool.',(110,360,500,182),38,24,True,'#ffe4e6')
d.line((120,580,600,580),fill='#fb7185',width=3)
fit(d,'Manufacturer-specific software may still be needed for setup, programming, and advanced functions.',(105,620,510,188),31,21)
fit(d,'Always check the device PICS document.',(113,836,494,75),28,19,True,'#fecdd3')
files.append(slides/'04_limitations.png'); im.convert('RGB').save(files[-1])
# 5 — Security
im,d=compose_base('BACnet & SECURITY', bg_security_network())
panel(d,(65,326,655,672),fill='#16304e',border='#60a5fa')
fit(d,'BACnet/IP',(100,352,520,75),40,25,True)
fit(d,'Traditional BACnet/IP is not encrypted by default.',(110,457,500,145),32,22)
panel(d,(65,710,655,1057),fill='#123c3c',border='#5eead4')
fit(d,'BACnet/SC',(100,739,520,75),40,25,True)
fit(d,'BACnet Secure Connect uses TLS to protect communication.',(110,839,500,145),32,22)
files.append(slides/'05_security.png'); im.convert('RGB').save(files[-1])

getdur=['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1']
duration=float(subprocess.check_output(getdur+[str(audio)],text=True).strip())
concat=job/'slides_v3.txt'
weights=[0.18,0.24,0.20,0.20,0.18]
with concat.open('w',encoding='utf-8') as f:
    for picture,weight in zip(files,weights):
        f.write(f"file '{picture}'\n")
        f.write(f'duration {duration*weight:.4f}\n')
    f.write(f"file '{files[-1]}'\n")

new=job/'video_layout_v3.mp4'
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(audio),'-t',f'{duration:.3f}','-vf','fps=24,format=yuv420p','-c:v','libx264','-preset','fast','-c:a','aac','-b:a','128k','-movflags','+faststart',str(new)],check=True)
actual=float(subprocess.check_output(getdur+[str(new)],text=True).strip())
if abs(actual-duration)>0.5:
    raise RuntimeError(f'Video/audio mismatch: {actual:.3f} vs {duration:.3f}')
original=job/'video.mp4'
backup=job/'video_before_background_fix.mp4'
if original.exists() and not backup.exists():
    shutil.copy2(original,backup)
os.replace(new,original)
reportfile=job/'production_report.json'
report=json.loads(reportfile.read_text(encoding='utf-8')) if reportfile.exists() else {}
report.update({'duration_seconds':round(actual,2),'speaker':'Andrew Chipper','voice_engine':'xtts','visual_layout':'auto-fit-v3-bg','background_opacity':'~8%','video':str(original)})
reportfile.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(f'BACKGROUND VIDEO PASSED: {len(files)} slides, all text fits.')
print(f'VIDEO REBUILT: {actual:.2f}s; XTTS audio: {duration:.2f}s')
print('Dashboard video updated with subtle background artwork.')
