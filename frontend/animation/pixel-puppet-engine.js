/* YapdOme Pixel Puppet v5 / procedural 48x48 RGB-indexed pixel robotics.
   Pixels remain hard-edged LED cells. Values 1..7 are material/light palette IDs. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports) module.exports=api;
  root.YapPixelEngine=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  const W=48,H=48;
  const EMOTIONS={
    neutral:{eye:2.3,browL:0,browR:0,smile:0,frown:0,open:0,round:0,pitch:0,yaw:0,gaze:0,cheek:0,spike:0,lid:0},
    joy:{eye:1.9,browL:.7,browR:.7,smile:1,frown:0,open:.12,round:0,pitch:-.35,yaw:.10,gaze:0,cheek:.7,spike:.2,lid:0},
    laugh:{eye:.8,browL:1.0,browR:1.0,smile:1,frown:0,open:.95,round:0,pitch:-.7,yaw:.2,gaze:0,cheek:1,spike:.4,lid:.6},
    angry:{eye:1.4,browL:-1.7,browR:-1.7,smile:0,frown:1,open:.3,round:0,pitch:.9,yaw:-.2,gaze:-.15,cheek:0,spike:.5,lid:.25},
    surprise:{eye:4.1,browL:2.1,browR:2.1,smile:0,frown:0,open:.9,round:1,pitch:-1.3,yaw:0,gaze:0,cheek:0,spike:1,lid:0},
    skeptic:{eye:1.7,browL:1.6,browR:-.8,smile:.25,frown:.25,open:0,round:0,pitch:.2,yaw:.55,gaze:.8,cheek:0,spike:0,lid:.4},
    sad:{eye:1.15,browL:1.15,browR:1.15,smile:0,frown:1,open:0,round:0,pitch:1.0,yaw:-.2,gaze:-.2,cheek:0,spike:0,lid:.35},
    smug:{eye:1.45,browL:-.4,browR:1.25,smile:.9,frown:0,open:.08,round:0,pitch:-.15,yaw:.45,gaze:.6,cheek:.7,spike:0,lid:.45},
    focus:{eye:1.05,browL:-.55,browR:-.55,smile:0,frown:0,open:0,round:0,pitch:.1,yaw:0,gaze:0,cheek:0,spike:.2,lid:.5},
    confused:{eye:2,browL:2,browR:-1,smile:.18,frown:.3,open:.16,round:0,pitch:.4,yaw:-.45,gaze:-.6,cheek:0,spike:.4,lid:.1}
  };
  const keys=Object.keys(EMOTIONS.neutral);
  const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
  class Raster{
    constructor(){this.a=new Uint8Array(W*H)}
    dot(x,y,v=3){x=Math.round(x);y=Math.round(y);if(x>=0&&y>=0&&x<W&&y<H){const i=y*W+x;if(v>this.a[i])this.a[i]=v}}
    erase(x,y){x=Math.round(x);y=Math.round(y);if(x>=0&&y>=0&&x<W&&y<H)this.a[y*W+x]=0}
    line(x0,y0,x1,y1,v=3){x0=Math.round(x0);y0=Math.round(y0);x1=Math.round(x1);y1=Math.round(y1);let dx=Math.abs(x1-x0),dy=-Math.abs(y1-y0),sx=x0<x1?1:-1,sy=y0<y1?1:-1,err=dx+dy;for(let k=0;k<140;k++){this.dot(x0,y0,v);if(x0===x1&&y0===y1)break;const e=2*err;if(e>=dy){err+=dy;x0+=sx}if(e<=dx){err+=dx;y0+=sy}}}
    rect(x,y,w,h,v=3,fill=false){x=Math.round(x);y=Math.round(y);w=Math.round(w);h=Math.round(h);if(fill){for(let yy=y;yy<y+h;yy++)for(let xx=x;xx<x+w;xx++)this.dot(xx,yy,v)}else{this.line(x,y,x+w-1,y,v);this.line(x,y+h-1,x+w-1,y+h-1,v);this.line(x,y,x,y+h-1,v);this.line(x+w-1,y,x+w-1,y+h-1,v)}}
    path(pts,v=3,closed=true){for(let i=0;i<pts.length-1;i++)this.line(...pts[i],...pts[i+1],v);if(closed)this.line(...pts.at(-1),...pts[0],v)}
    fill(pts,v=1){if(pts.length<3)return;const ys=pts.map(p=>p[1]);let min=Math.max(0,Math.floor(Math.min(...ys))),max=Math.min(H-1,Math.ceil(Math.max(...ys)));for(let y=min;y<=max;y++){let xs=[],q=y+.5;for(let i=0;i<pts.length;i++){const a=pts[i],b=pts[(i+1)%pts.length];if((a[1]<=q&&b[1]>q)||(b[1]<=q&&a[1]>q))xs.push(a[0]+(q-a[1])*(b[0]-a[0])/(b[1]-a[1]))}xs.sort((a,b)=>a-b);for(let i=0;i+1<xs.length;i+=2)for(let x=Math.ceil(xs[i]);x<xs[i+1];x++)this.dot(x,y,v)}}
    clearRect(x,y,w,h){for(let yy=Math.round(y);yy<Math.round(y+h);yy++)for(let xx=Math.round(x);xx<Math.round(x+w);xx++)this.erase(xx,yy)}
  }
  function draw(id,pose,meta={}){
    const p={...EMOTIONS.neutral,...pose};const r=new Raster();
    const t=meta.t||0,talk=clamp(meta.talk||0,0,1),blink=clamp(meta.blink||0,0,1),beat=clamp(meta.beat||0,0,1);
    const yaw=clamp(p.yaw,-1,1), nod=clamp(p.pitch,-1.4,1.4);
    const phase=id==='norman'?0:id==='glitch'?2.1:4.2;
    const shiftX=yaw*2.35+Math.sin(t*.55+phase)*.18;
    const shiftY=nod*.9+Math.sin(t*1.35+phase)*.24+beat*.48;
    const HX=(x,y)=>Math.round(24+(x-24)*(1-.075*Math.abs(yaw))+shiftX+(y-20)*yaw*.036);
    const HY=(x,y)=>Math.round(y+shiftY+(x-24)*yaw*.032);
    const hd=(x,y,v=3)=>r.dot(HX(x,y),HY(x,y),v);
    const he=(x,y)=>r.erase(HX(x,y),HY(x,y));
    const hl=(x,y,x2,y2,v=3)=>r.line(HX(x,y),HY(x,y),HX(x2,y2),HY(x2,y2),v);
    const hpath=(pts,v=3,closed=true)=>r.path(pts.map(([x,y])=>[HX(x,y),HY(x,y)]),v,closed);
    const hfill=(pts,v=1)=>r.fill(pts.map(([x,y])=>[HX(x,y),HY(x,y)]),v);
    const gaze=Math.round((p.gaze+yaw*.35)*1.45);
    // torso and neck under the head
    r.fill([[6,47],[8,40],[14,36],[19,34],[29,34],[34,36],[40,40],[42,47]],1);
    r.path([[6,47],[8,40],[14,36],[19,34],[29,34],[34,36],[40,40],[42,47]],2,false);
    r.line(15,37,11,47,3);r.line(33,37,37,47,3);
    r.line(20,37,19,47,2);r.line(28,37,29,47,2);
    r.fill([[20,34],[20,30],[28,30],[28,34]],1);r.rect(21,31,6,3,2,false);r.rect(23,32,2,1,3,true);
    r.rect(18,40,12,4,2,false);r.rect(21,41,6,2,3,true);
    // special torso glyphs
    if(id==='glitch'){r.line(21,38,27,44,2);r.line(27,38,21,44,3)}
    if(id==='jessie'){r.path([[21,39],[24,42],[27,39],[29,41],[24,46],[19,41]],2);r.dot(24,42,3)}
    if(id==='norman'){r.line(21,36,23,38,2);r.line(27,36,25,38,2)}
    // Layered chest plating, status rail and a live speech reactor.
    r.path([[16,39],[19,37],[29,37],[32,39]],2,false);
    r.line(18,44,30,44,4);r.rect(22,40,4,2,4,false);
    r.line(20,46,28,46,2);
    if(beat>.18){r.rect(23,41,2,1,5,true);r.dot(24,43,5)}

    if(id==='norman'){
      // five-point electro crown, rigid ear modules
      const crown=[[12,17],[8,14],[12,13],[9,9],[15,12],[14,5],[21,10],[24,2-Math.round(p.spike*.6)],[27,10],[34,5],[32,12],[39,9],[36,15],[37,18]];
      hfill(crown,1);hpath(crown,3);
      const shell=[[13,15],[16,12],[32,12],[35,15],[35,27],[32,33],[28,36],[20,36],[16,33],[13,27]];
      hfill(shell,1);hpath(shell,3);
      hfill([[16,17],[32,17],[32,29],[28,33],[20,33],[16,29]],2);
      hl(15,20,15,29,2);hl(33,20,33,29,2);
      r.rect(10,21,3,4,2,false);r.rect(36,21,3,4,2,false);
      hd(24,6,3);hd(11,23,3);hd(37,23,3);
      // goggles + lower jaw as distinct mechanical modules
      for(let y=18;y<=27;y++)for(let x=17;x<=31;x++)he(x,y);
      for(let y=29;y<=34;y++)for(let x=18;x<=30;x++)he(x,y);
      hl(17,18,31,18,3);hl(17,27,31,27,2);
      // Crown circuitry and cheek-side power rails.
      hpath([[12,15],[15,13],[18,14]],4,false);hpath([[30,14],[33,12],[36,15]],4,false);
      hd(24,6,5);hl(23,9,24,12,4);hl(24,12,25,14,5);
      drawFace('norman',r,{hd,hl,hpath,hfill,he,HX,HY,gaze},p,talk,blink,beat);
      hl(17,32,20,36,2);hl(31,32,28,36,2);hl(20,36,28,36,3);
      hd(14,25,4);hd(34,25,4);hd(24,34,5);
    }
    else if(id==='glitch'){
      // terminal hood: slim face enclosed by oversized glowing cloth-shell
      const hood=[[5,34],[7,26],[9,20],[11,13],[18,7],[22,4],[26,4],[32,8],[38,15],[41,27],[43,37],[39,43],[32,39],[29,35],[19,35],[16,39],[9,43]];
      hfill(hood,1);hpath(hood,3);
      hpath([[10,34],[11,24],[16,15],[22,9],[26,8],[34,17],[37,27],[38,36]],2,false);
      hpath([[15,14],[22,7],[28,8],[34,16]],3,false);
      hpath([[12,17],[18,10],[23,8]],4,false);hpath([[29,8],[34,12],[37,19]],4,false);
      hd(24,6,5);hd(13,20,4);hd(35,20,4);
      // folded hood seams
      hl(10,28,8,38,2);hl(38,28,40,38,2);hl(12,35,17,31,2);hl(36,35,31,31,2);
      const mask=[[17,19],[20,15],[28,15],[32,19],[31,29],[28,34],[20,34],[17,29]];
      hfill(mask,2);hpath(mask,3);
      hfill([[19,20],[29,20],[29,29],[26,31],[22,31],[19,29]],1);
      for(let y=20;y<=27;y++)for(let x=19;x<=29;x++)he(x,y);
      for(let y=29;y<=32;y++)for(let x=20;x<=28;x++)he(x,y);
      drawFace('glitch',r,{hd,hl,hpath,hfill,he,HX,HY,gaze},p,talk,blink,beat);
      // machine teeth on hood hem
      hl(9,39,17,35,2);hl(31,35,39,39,2);
      hd(12,20,3);hd(36,21,3);hd(24,7,3);
      // periodic corrupt data bits, only squared cells
      if((meta.glitch||0)>.35){let gy=18+Math.floor((t*13)%16);for(let x=13;x<37;x+=3){const xx=HX(x,gy),yy=HY(x,gy);r.erase(xx,yy);r.dot(xx+1,yy,5)}}
      if(beat>.7){hd(14,32,5);hd(34,32,5)}
    }
    else if(id==='jessie'){
      // robot cable locks: thick modular curls on left and right
      const locks=[
        [[15,12],[10,14],[8,20],[9,27],[7,35],[9,42]],
        [[18,10],[13,10],[10,16],[11,25],[8,31],[10,38]],
        [[30,10],[35,12],[38,18],[37,25],[40,32],[38,41]],
        [[33,13],[39,15],[41,22],[39,27],[42,35],[40,43]]
      ];
      locks.forEach((arr,i)=>{hpath(arr,3,false);hpath(arr.map(([x,y])=>[x+(i<2?2:-2),y+1]),i%2===0?4:2,false)});
      const crown=[[14,17],[15,12],[19,9],[23,8],[29,9],[33,12],[34,17]];
      hfill(crown,2);hpath(crown,3);
      const face=[[16,17],[18,13],[29,13],[33,17],[34,26],[31,33],[27,36],[21,36],[17,33],[14,27]];
      hfill(face,1);hpath(face,3);
      hfill([[17,19],[31,19],[32,26],[29,33],[20,33],[16,26]],2);
      // cheek side speakers and earrings
      r.rect(11,23,3,4,2,false);r.rect(35,23,3,4,2,false);
      hd(12,27,3);hd(36,27,3);hd(19,12,3);hd(29,12,3);
      for(let y=19;y<=27;y++)for(let x=17;x<=31;x++)he(x,y);
      for(let y=29;y<=33;y++)for(let x=19;x<=29;x++)he(x,y);
      drawFace('jessie',r,{hd,hl,hpath,hfill,he,HX,HY,gaze},p,talk,blink,beat);
      // Signature cable locks, status gems and cheek speakers.
      hd(9,31,4);hd(39,31,4);hd(19,12,5);hd(29,12,5);
      hl(12,34,15,37,4);hl(36,34,33,37,4);
      if(p.cheek>.4){hd(15,29,5);hd(33,29,5)}
    }
    return r.a;
  }
  function drawFace(id,r,d,p,talk,blink,beat){
    const {hd,hl,hpath,hfill,HX,HY,gaze}=d;
    const openness=Math.max(.05,p.eye*(1-blink));
    const sm=p.smile,fr=p.frown, o=clamp(Math.max(p.open,talk*.93),0,1),round=p.round;
    let left=20,right=28,baseline=20, browY=17;
    if(id==='norman'){left=20;right=28;baseline=20;browY=16}
    if(id==='glitch'){left=21;right=27;baseline=21;browY=18}
    if(id==='jessie'){left=20;right=28;baseline=21;browY=17}
    const shift=clamp(gaze,-2,2);
    const bx1=Math.round(-p.browL*1.25), bx2=Math.round(-p.browR*1.25);
    const tense=p.frown>.5?1:0;
    hl(left-3+shift,browY+bx1,left+2+shift,browY+bx1+tense*2,3);
    hl(right-2+shift,browY+bx2+tense*2,right+3+shift,browY+bx2,3);
    function eye(cx,ey,extent){
      const open=clamp(Math.round(extent),0,5);
      if(open<2){hl(cx-2+shift,ey,cx+2+shift,ey,4);return}
      const w=id==='glitch'?2:3;
      for(let y=0;y<open;y++){
        const ww=(y===0||y===open-1)?w-1:w;
        hl(cx-ww+shift,ey+y,cx+ww+shift,ey+y,6);
      }
      hd(cx+shift+Math.sign(p.gaze)*1,ey+Math.min(1,open-1),7);
      if(open>3)hd(cx+shift,ey+2,6);
      hd(cx-1+shift,ey,7);
    }
    if(p.smile>.85&&o>.75){
      hl(left-2+shift,baseline+1,left+2+shift,baseline+2,3);
      hl(right-2+shift,baseline+2,right+2+shift,baseline+1,3);
    }else if(id==='glitch'){
      eye(left,baseline,Math.max(.5,openness-.25));eye(right,baseline,Math.max(.5,openness-.25));
      if(p.frown>.3){hd(left-2,baseline-1,3);hd(right+2,baseline-1,3)}
    }else{eye(left,baseline,openness);eye(right,baseline,openness*.97)}
    if(id!=='glitch'){hd(24+shift,26,4);hd(24+shift,27,4)}
    else hd(24+shift,27,5);
    // actual mouth LEDs changing geometry, never overlay images
    let y=id==='glitch'?30:30;
    if(id==='jessie')y=30;
    const mw=id==='glitch'?4:6;
    if(round>.55){
      const hh=3+Math.round(o*3);
      const ww=3+Math.round(o);
      let xx=24-Math.floor(ww/2);
      for(let py=0;py<hh;py++)for(let px=0;px<ww;px++){
        if(py===0||py===hh-1||px===0||px===ww-1)hd(xx+px,y+py,3);
        else hd(xx+px,y+py,1);
      }
    }else if(o>.55){
      const hh=2+Math.round(o*2.5), half=mw;
      hpath([[24-half,y],[24+half,y],[24+half-1,y+hh],[24-half+1,y+hh]],3);
      hfill([[24-half+1,y+1],[24+half-1,y+1],[24+half-2,y+hh-1],[24-half+2,y+hh-1]],1);
      hl(24-half+2,y+hh-1,24+half-2,y+hh-1,2);
    }else if(o>.2){
      hpath([[24-mw,y],[24+mw,y],[24+mw-1,y+2],[24-mw+1,y+2]],3);
    }else if(fr>.5){
      hl(24-mw,y+2,24-mw+2,y+1,3);hl(24-mw+2,y+1,24+mw-2,y+1,3);hl(24+mw-2,y+1,24+mw,y+2,3);
    }else if(sm>.4){
      hl(24-mw,y,24-mw+2,y+2,3);hl(24-mw+2,y+2,24+mw-2,y+2,3);hl(24+mw-2,y+2,24+mw,y,3);
      if(sm>.9)hl(24-mw+2,y+1,24+mw-2,y+1,2);
    }else if(sm>.1){
      hl(24-4,y+1,24+4,y+1,3);hd(29,y,3);
    }else{hl(21,y+1,27,y+1,3)}
    // cheeks and speech actuators
    if(p.cheek>.35){hd(16,28,4);hd(32,28,4);if(id==='jessie'){hd(17,29,5);hd(31,29,5)}}
    if(fr>.65){hl(17,27,19,28,2);hl(29,28,31,27,2)}
    if(beat>.65){hd(15,31,5);hd(33,31,5)}
  }
  return {W,H,EMOTIONS,keys,draw,clamp};
});
