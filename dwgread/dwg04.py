import struct,sys
def dec_hdr(b):
    out=bytearray();seed=1
    for x in b:
        seed=(seed*0x343FD+0x269EC3)&0xFFFFFFFF;out.append(x^((seed>>16)&0xFF))
    return bytes(out)
class R:
    def __init__(s,b):s.b=b;s.i=0
    def rc(s):v=s.b[s.i];s.i+=1;return v
def litlen(r):
    b=r.rc()
    if 1<=b<=0x0F:return b+3,0
    if b==0:
        t=0x0F
        while True:
            b=r.rc()
            if b!=0:break
            t+=0xFF
        return t+b+3,0
    return 0,b
def longoff(r):
    b=r.rc();t=0
    if b==0:
        t=0xFF
        while True:
            b=r.rc()
            if b!=0:break
            t+=0xFF
    return t+b
def twooff(r):
    a=r.rc();c=r.rc();return (a>>2)|(c<<6),a&3
def decomp(src,dsize):
    r=R(src);dst=bytearray()
    ll,op=litlen(r);dst+=src[r.i:r.i+ll];r.i+=ll
    while r.i<len(src):
        if op==0:op=r.rc()
        if op>=0x40:
            cb=((op&0xF0)>>4)-1;o2=r.rc();co=(o2<<2)|((op&0x0C)>>2);ll=op&3
        elif op>=0x21:
            cb=op-0x1E;co,ll=twooff(r)
        elif op==0x20:
            cb=longoff(r)+0x21;co,ll=twooff(r)
        elif op>=0x12:
            cb=(op&0x0F)+2;co,ll=twooff(r);co+=0x3FFF
        elif op==0x10:
            cb=longoff(r)+9;co,ll=twooff(r);co+=0x3FFF
        elif op==0x11:break
        else:raise ValueError('op %x at %d'%(op,r.i))
        s=len(dst)-co-1
        for k in range(cb):dst.append(dst[s+k])
        if ll==0:
            ll,op=litlen(r)
        else:op=0
        dst+=src[r.i:r.i+ll];r.i+=ll
    return bytes(dst)
def sections(path):
    f=open(path,'rb').read()
    h=dec_hdr(f[0x80:0x80+0x6C])
    assert h[:11]==b'AcFssFcAJMB',h[:12]
    pmid,=struct.unpack_from('<I',h,0x50);pmaddr,=struct.unpack_from('<Q',h,0x54);smid,=struct.unpack_from('<I',h,0x5C)
    a=pmaddr+0x100
    t,ds,cs,ct,ck=struct.unpack_from('<5I',f,a)
    pm=decomp(f[a+20:a+20+cs],ds)
    pages={};addr=0x100;i=0
    while i+8<=len(pm):
        n,sz=struct.unpack_from('<ii',pm,i);i+=8
        if n<0:i+=16
        else:pages[n]=addr
        addr+=sz
    a=pages[smid];t,ds,cs,ct,ck=struct.unpack_from('<5I',f,a)
    sm=decomp(f[a+20:a+20+cs],ds)
    nd,=struct.unpack_from('<I',sm,0);i=20;out={}
    for _ in range(nd):
        size,pc,maxd,unk,comp,sid,enc=struct.unpack_from('<QIIIIII',sm,i);i+=32
        name=sm[i:i+64].split(b'\0')[0].decode('latin1');i+=64
        pl=[]
        for _ in range(pc):
            pn,dsz,so=struct.unpack_from('<IIQ',sm,i);i+=16;pl.append((pn,dsz,so))
        out[name]=dict(size=size,comp=comp,enc=enc,maxd=maxd,pages=pl)
    return f,pages,out
def read_section(f,pages,info):
    buf=bytearray(info['size'])
    for pn,dsz,so in info['pages']:
        a=pages[pn]
        mask=0x4164536b^a
        hd=struct.unpack_from('<8I',f,a);hd=[x^mask for x in hd]
        csz=hd[2]
        raw=f[a+32:a+32+csz]
        d=decomp(raw,info['maxd']) if info['comp']==2 else raw
        buf[so:so+len(d)]=d[:max(0,min(len(d),info['size']-so))]
    return bytes(buf)
if __name__=='__main__':
    f,p,s=sections(sys.argv[1])
    for k,v in s.items():print(k,v['size'],len(v['pages']),v['comp'],v['enc'])
