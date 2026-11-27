import sys,struct,collections;from .dwg04 import *
class Bits:
    def __init__(s,b,pos=0):s.b=b;s.p=pos
    def B(s):
        v=(s.b[s.p>>3]>>(7-(s.p&7)))&1;s.p+=1;return v
    def n(s,k):
        v=0
        for _ in range(k):v=(v<<1)|s.B()
        return v
    def RC(s):return s.n(8)
    def RS(s):a=s.RC();b=s.RC();return a|(b<<8)
    def RL(s):a=s.RS();b=s.RS();return a|(b<<16)
    def RD(s):return struct.unpack('<d',bytes(s.RC() for _ in range(8)))[0]
    def BB(s):return s.n(2)
    def BS(s):
        c=s.BB();return [s.RS,s.RC,lambda:0,lambda:256][c]()
    def BL(s):
        c=s.BB();return [s.RL,s.RC,lambda:0,lambda:0][c]()
    def BLL(s):
        l=s.n(3);v=0
        for i in range(l):v|=s.RC()<<(8*i)
        return v
    def BD(s):
        c=s.BB();return [s.RD,lambda:1.0,lambda:0.0,lambda:None][c]()
    def DD(s,dflt):
        c=s.BB()
        if c==0:return dflt
        db=bytearray(struct.pack('<d',dflt))
        if c==1:
            for i in range(4):db[i]=s.RC()
        elif c==2:
            db[4]=s.RC();db[5]=s.RC()
            for i in range(4):db[i]=s.RC()
        else:return s.RD()
        return struct.unpack('<d',bytes(db))[0]
    def H(s):
        code=s.n(4);cnt=s.n(4);v=0
        for _ in range(cnt):v=(v<<8)|s.RC()
        return code,v
    def BE(s):
        if s.B():return (0,0,1)
        return (s.BD(),s.BD(),s.BD())
    def BT(s):
        return 0.0 if s.B() else s.BD()
def MC(b,i,signed):
    v=0;sh=0
    while True:
        c=b[i];i+=1
        if c&0x80:v|=(c&0x7f)<<sh;sh+=7
        else:
            if signed:
                neg=c&0x40;v|=(c&0x3f)<<sh
                if neg:v=-v
            else:v|=(c&0x7f)<<sh
            return v,i
def MS(b,i):
    v=0;sh=0
    while True:
        w=b[i]|(b[i+1]<<8);i+=2
        if w&0x8000:v|=(w&0x7fff)<<sh;sh+=15
        else:v|=w<<sh;return v,i
def objmap(f,pg,s):
    h=read_section(f,pg,s['AcDb:Handles']);i=0;m={}
    while i<len(h):
        size=(h[i]<<8)|h[i+1]
        if size==2:break
        st=i+2;end=i+size;j=st;hd=0;od=0
        while j<end:
            a,j=MC(h,j,False);b,j=MC(h,j,True);hd+=a;od+=b;m[hd]=od
        i=end+2
    return m
def load(path):
    f,pg,s=sections(path);ver=f[:6].decode()
    obj=read_section(f,pg,s['AcDb:AcDbObjects']);return ver,obj,objmap(f,pg,s),s
if __name__=='__main__':
    ver,obj,m,s=load(sys.argv[1]);R2010=ver>='AC1024'
    c=collections.Counter()
    for hnd,off in m.items():
        size,i=MS(obj,off)
        if R2010:hs,i=MC(obj,i,False)
        bt=Bits(obj,i*8)
        if R2010:
            k=bt.BB();t=bt.RC() if k==0 else (bt.RC()+0x1f0 if k==1 else bt.RS())
        else:t=bt.BS()
        c[t]+=1
    print(ver,len(m),sorted(c.items()))
