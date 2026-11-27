import sys,struct,collections,json;from .objs import *
def parse(path,nolinks_mode):
    ver,obj,m,s=load(path);R2007=ver>='AC1021';R2010=ver>='AC1024';R2013=ver>='AC1027'
    out=[];layers={};blocks={};errs=collections.Counter()
    for hnd,off in m.items():
      try:
        size,i=MS(obj,off);hs=0
        if R2010:hs,i=MC(obj,i,False)
        base=i*8;bt=Bits(obj,base)
        if R2010:
            k=bt.BB();t=bt.RC() if k==0 else (bt.RC()+0x1f0 if k==1 else bt.RS())
            bitsize=size*8-hs
        else:
            t=bt.BS();bitsize=bt.RL()
        if t not in (1,7,11,16,17,18,19,27,44,77,78,51,49,2,3):continue
        def sstream():
            if not R2007:return None
            st=bitsize-1;q=Bits(obj,base+st)
            if not q.B():return None
            st-=16;q=Bits(obj,base+st);ds=q.RS()
            if ds&0x8000:
                st-=16;q=Bits(obj,base+st);hi=q.RS();ds=(ds&0x7fff)|(hi<<15)
            st-=ds;return Bits(obj,base+st)
        ss=sstream()
        def T(main):
            if R2007:
                q=ss;n=q.BS();return ''.join(chr(q.RS()) for _ in range(n)).rstrip('\0')
            n=main.BS();return bytes(main.RC() for _ in range(n)).decode('cp1251','replace')
        hc,hv=bt.H()
        while True:
            sz=bt.BS()
            if sz==0:break
            bt.H();bt.p+=8*sz
        if t in (51,49):
            bt.BL();bt.B()
            if R2013:bt.B()
            name=T(bt)
            (layers if t==51 else blocks)[hnd]=name;continue
        if bt.B():
            gs=bt.BLL() if R2010 else bt.RL();bt.p+=8*gs
        em=bt.BB();nr=bt.BL();xm=bt.B()
        if R2013:bt.B()
        if nolinks_mode:bt.B()
        ci=bt.BS();fl=ci>>8
        if fl&0x80:bt.BL()
        if fl&0x20:bt.BL()
        bt.BD();ltf=bt.BB();psf=bt.BB()
        if R2007:mf=bt.BB();bt.RC()
        else:mf=0
        if R2010:vs=[bt.B(),bt.B(),bt.B()]
        else:vs=[0,0,0]
        bt.BS();bt.RC()
        e={'h':hnd,'t':t}
        if t==19:
            z=bt.B();x0=bt.RD();x1=bt.DD(x0);y0=bt.RD();y1=bt.DD(y0)
            e['pts']=[(x0,y0),(x1,y1)]
        elif t==77:
            fg=bt.BS()
            if fg&4:bt.BD()
            if fg&8:bt.BD()
            if fg&2:bt.BD()
            if fg&1:bt.BD();bt.BD();bt.BD()
            n=bt.BL();nb=bt.BL() if fg&16 else 0
            if R2010 and fg&1024:bt.BL()
            nw=bt.BL() if fg&32 else 0
            if n>100000:raise ValueError('n')
            p=[];x=bt.RD();y=bt.RD();p.append((x,y))
            for _ in range(n-1):x=bt.DD(x);y=bt.DD(y);p.append((x,y))
            e['pts']=p;e['closed']=bool(fg&512);e['bulge']=[bt.BD() for _ in range(nb)]
        elif t==1:
            df=bt.RC()
            if not df&1:bt.RD()
            x=bt.RD();y=bt.RD()
            if not df&2:bt.DD(x);bt.DD(y)
            bt.BE();bt.BT()
            if not df&4:bt.RD()
            rot=0 if df&8 else bt.RD()
            hgt=bt.RD()
            if not df&16:bt.RD()
            e['pts']=[(x,y)];e['txt']=T(bt);e['hgt']=hgt;e['rot']=rot
        elif t==44:
            x=bt.BD();y=bt.BD();bt.BD();bt.BE() if False else (bt.BD(),bt.BD(),bt.BD());bt.BD();bt.BD();bt.BD()
            if R2007:bt.BD()
            bt.BD();hgt=bt.BD();bt.BS();bt.BS();bt.BD();bt.BD()
            e['pts']=[(x,y)];e['txt']=T(bt);e['hgt']=hgt
        elif t in (17,18):
            x=bt.BD();y=bt.BD();bt.BD();r=bt.BD();e['pts']=[(x,y)];e['r']=r
            if t==17:bt.BT();bt.BE();e['a']=(bt.BD(),bt.BD())
        elif t==27:
            e['pts']=[(bt.BD(),bt.BD())]
        elif t==7:
            e['pts']=[(bt.BD(),bt.BD())];bt.BD()
            sf=bt.BB()
            if sf==3:pass
            elif sf==1:bt.DD(1.0);bt.DD(1.0)
            else:sx=bt.RD();bt.DD(sx);bt.DD(sx)
            e['rot']=bt.BD()
        elif t==11:
            bt.RC();e['pts']=[(bt.BD(),bt.BD())];bt.BD()
        elif t==16:
            bt.RC();bt.RC();e['n']=bt.BL();e['pts']=[]
        elif t==78:
            g=bt.BL();bt.BL();bt.BD();bt.BD();bt.BL();bt.BD();nc=bt.BL()
            for _ in range(nc):
                bt.BD();ci2=bt.BS();rgb=bt.BL();cf=bt.RC()
                if cf&1:T(bt)
                if cf&2:T(bt)
            if R2007:
                if ss is not None:pass
            gname=T(bt) if True else ''
            bt.BD();bt.BD();bt.BD();bt.BD()
            pname=T(bt);solid=bt.B();bt.B();npath=bt.BL();paths=[]
            if npath>10000:raise ValueError('np')
            for _ in range(npath):
                pf=bt.BL();pp=[]
                if not pf&2:
                    ns=bt.BL()
                    for _ in range(ns):
                        st=bt.RC()
                        if st==1:a=(bt.RD(),bt.RD());b=(bt.RD(),bt.RD());pp+=[a,b]
                        elif st==2:c=(bt.RD(),bt.RD());r=bt.BD();sa=bt.BD();ea=bt.BD();ccw=bt.B();pp.append(c)
                        elif st==3:c=(bt.RD(),bt.RD());bt.RD();bt.RD();bt.BD();bt.BD();bt.BD();bt.B();pp.append(c)
                        else:raise ValueError('spline')
                else:
                    hb=bt.B();cl=bt.B();nv=bt.BL()
                    for _ in range(nv):
                        pp.append((bt.RD(),bt.RD()))
                        if hb:bt.BD()
                nbo=bt.BL();paths.append(pp)
            e['paths']=paths;e['pts']=paths[0][:1] if paths and paths[0] else [];e['pat']=pname;e['solid']=solid
        else:continue
        # handle stream -> layer
        q=Bits(obj,base+bitsize)
        if em==0:q.H()
        for _ in range(nr):q.H()
        if not xm:q.H()
        lc,lv=q.H()
        e['layer_h']=lv if lc<6 else {6:hnd+1,8:hnd-1,0xA:hnd+lv,0xC:hnd-lv}.get(lc)
        if t in(7,16):
            if ltf==3:q.H()
            if fl&0x40:q.H()
            if mf==3:q.H()
            if psf==3:q.H()
            for v in vs:
                if v:q.H()
            if t==7:
                bc,bv=q.H();e['block_h']=bv if bc<6 else None
            else:
                own=[]
                for _ in range(e['n']):
                    c2,v2=q.H();own.append(v2 if c2<6 else {6:hnd+1,8:hnd-1,0xA:hnd+v2,0xC:hnd-v2}.get(c2))
                e['own']=own
        out.append(e)
      except Exception as ex:errs[type(ex).__name__]+=1
    for e in out:
        e['layer']=layers.get(e.pop('layer_h'),'?')
        if 'block_h' in e:e['block']=blocks.get(e.pop('block_h'),'?')
    return ver,out,layers,errs
if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    for nl in (0,1):
        ver,out,L,er=parse(sys.argv[1],nl)
        ok=sum(1 for e in out if e['layer']!='?')
        print('nolinks',nl,len(out),'layer ok',ok,dict(er),list(L.values())[:5])
