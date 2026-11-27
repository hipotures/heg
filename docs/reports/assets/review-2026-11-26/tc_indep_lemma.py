# Review follow-up 2 (2026-11-27). Requires python-sat (CaDiCaL). Usage: python3 tc_indep_lemma.py
# Independent re-encoding (review 2026-11-27) of TC + {H15, G2} lifts as SAT; solved with CaDiCaL (PySAT).
# TC built as Levi graph of GQ(2,2) (not LCF); own cycle enumeration; own PB->CNF (monotone prefix-sum DP).
import itertools, sys, time
from pysat.card import CardEnc, EncType
from pysat.solvers import Cadical153
P=list(itertools.combinations(range(6),2))
def pms(s):
    if not s: yield []; return
    a=s[0]
    for b in s[1:]:
        for t in pms([x for x in s if x not in (a,b)]): yield [(a,b)]+t
M=list(pms(list(range(6))))
adj={i:set() for i in range(30)}
for i,p in enumerate(P):
    for j,m in enumerate(M):
        if p in m: adj[i].add(15+j); adj[15+j].add(i)
nb={v:sorted(adj[v]) for v in range(30)}
cyc=[]
for s in range(30):
    st=[(s,(s,))]
    while st:
        v,p=st.pop()
        for w in nb[v]:
            if w==s and len(p) in (8,10) and p[1]<p[-1]: cyc.append(p)
            elif w>s and w not in p and len(p)<10: st.append((w,p+(w,)))
L8=sum(len(c)==8 for c in cyc); print("TC cycles: C8=%d C10=%d"%(L8,len(cyc)-L8))
assert L8==90 and len(cyc)-L8==72
def w_of(t,p,off,g2):   # w = dl-2
    if t==0: return 3 if p==off else 1          # H15 (3,3,5): special = complement of 5-pair
    if g2=='H7':  return 1 if p==off else 0     # H7 (2,2,3): special = complement of 3-pair
    return 0 if p==off else 1                   # H8* (2,3,3): special = complement of 2-pair
def solve(a,g2,symbreak=True,lemma=True):
    nv=[0]
    def new(): nv[0]+=1; return nv[0]
    x={(v,t,p):new() for v in range(30) for t in (0,1) for p in range(3)}
    cl=[]
    for v in range(30):
        vs=[x[v,t,p] for t in (0,1) for p in range(3)]
        cl.append(vs); cl+= [[-a_,-b_] for a_,b_ in itertools.combinations(vs,2)]
    card=CardEnc.atmost(lits=[x[v,0,p] for v in range(30) for p in range(3)],bound=a,top_id=nv[0],encoding=EncType.seqcounter)
    nv[0]=max(nv[0],card.nv); cl+=card.clauses
    for c in cyc:
        Lc=len(c); K=33-3*Lc
        # r[i][s]: prefix of first i vertices has sum >= s  (one-directional: r -> real prefix sum >= s)
        r={(0,0):None}
        for i in range(1,Lc+1):
            for s in range(1,K+1): r[i,s]=new()
        def R(i,s):
            if s<=0: return None      # always true
            if i==0: return False     # prefix 0 has sum 0
            return r[i,s]
        for i in range(1,Lc+1):
            v=c[i-1]; prev=c[i-2]; nxt=c[i % Lc]
            off=[k for k,u in enumerate(nb[v]) if u not in (prev,nxt)]; assert len(off)==1; off=off[0]
            for s in range(1,K+1):
                for t in (0,1):
                    for p in range(3):
                        tgt=R(i-1,s-w_of(t,p,off,g2))
                        if tgt is None: continue
                        if tgt is False: cl.append([-x[v,t,p],-r[i,s]])
                        else: cl.append([-x[v,t,p],-r[i,s],tgt])
        cl.append([r[Lc,K]])
    if lemma:
        # Counting lemma (hand-verified): sum over the 90 C8 of (sum_w - 9) = 16a-8b-16c-90 =: S for the
        # actual counts; with AtMost(#H15<=a) the actual value is <= S(a). Encode excess via upward
        # (forced-true) prefix indicators q[i][s] and AtMost(sum_k [sum_w >= 9+k], S).
        Sb=16*a-(8 if g2=='H8*' else 16)*(30-a)-90
        exc=[]
        for c in cyc:
            if len(c)!=8: continue
            q={}
            for i in range(1,9):
                for t_ in range(1,25): q[i,t_]=new()
            for i in range(1,9):
                v=c[i-1]; prev=c[i-2]; nxt=c[i % 8]
                off=[k for k,u in enumerate(nb[v]) if u not in (prev,nxt)][0]
                for t_ in range(1,25):
                    if i>1: cl.append([-q[i-1,t_],q[i,t_]])
                    for t in (0,1):
                        for p in range(3):
                            w=w_of(t,p,off,g2)
                            if w==0: continue
                            if t_-w<=0: cl.append([-x[v,t,p],q[i,t_]])
                            elif i>1: cl.append([-x[v,t,p],-q[i-1,t_-w],q[i,t_]])
            exc+=[q[8,9+k] for k in range(1,16)]
        ce=CardEnc.atmost(lits=exc,bound=Sb,top_id=nv[0],encoding=EncType.seqcounter)
        nv[0]=max(nv[0],ce.nv); cl+=ce.clauses
    if symbreak: cl.append([x[0,1,0]])
    t0=time.time()
    with Cadical153(bootstrap_with=cl) as S:
        res=S.solve(); model=S.get_model() if res else None
    dt=time.time()-t0
    if res:  # independent model check
        val=set(l for l in model if l>0)
        st={v:[(t,p) for t in (0,1) for p in range(3) if x[v,t,p] in val][0] for v in range(30)}
        assert sum(1 for v in st if st[v][0]==0)<=a
        for c in cyc:
            Lc=len(c); tot=0
            for i,v in enumerate(c):
                prev=c[i-1]; nxt=c[(i+1)%Lc]; off=[k for k,u in enumerate(nb[v]) if u not in (prev,nxt)][0]
                tot+=w_of(*st[v],off,g2)
            assert tot>=33-3*Lc
        nh=sum(1 for v in st if st[v][0]==0)
        n=15*nh+(8 if g2=='H8*' else 7)*(30-nh)
        return "SAT (model checked, #H15=%d, n=%d)"%(nh,n),dt,nv[0],len(cl)
    return "UNSAT",dt,nv[0],len(cl)
for a,g2,sb in [(18,'H7',True),(14,'H8*',True),(20,'H7',True),(15,'H8*',True)]:
    res,dt,nvv,ncl=solve(a,g2,sb)
    print(f"a15<={a:2d} G2={g2:3s} symbreak={sb!s:5s} vars={nvv} clauses={ncl}: {res}  ({dt:.1f}s)",flush=True)
