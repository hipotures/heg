# Review 2026-11-26: H8* windows/internal cycles + Petersen 5-cycle data for pet.c
import itertools
E=[(0,3),(0,4),(1,3),(1,6),(2,5),(2,7),(3,5),(4,6),(4,7),(5,7),(6,7)]
n=8; adj={i:set() for i in range(n)}
for a,b in E: adj[a].add(b); adj[b].add(a)
print("deg",[len(adj[i]) for i in range(n)])
def paths(s,t):
    out=set(); st=[(s,[s])]
    while st:
        v,p=st.pop()
        for w in adj[v]:
            if w==t: out.add(len(p)); continue
            if w in p: continue
            st.append((w,p+[w]))
    return sorted(out)
for a,b in [(0,1),(0,2),(1,2)]: print("S",a,b,paths(a,b))
cyc=set()
for s in range(n):
    st=[(s,[s])]
    while st:
        v,p=st.pop()
        for w in adj[v]:
            if w==s and len(p)>=3: cyc.add(len(p))
            elif w not in p and w>s: st.append((w,p+[w]))
print("internal cycles",sorted(cyc))
# Petersen exhaustive check of r=2 (8 H7 + 2 H8*), r=1, r=3 on min-windows only
O=[(i,(i+1)%5) for i in range(5)]+[(i,i+5) for i in range(5)]+[(5+i,5+(i+2)%5) for i in range(5)]
pa={i:set() for i in range(10)}
for a,b in O: pa[a].add(b); pa[b].add(a)
C5=set()
for c in itertools.permutations(range(10),5):
    if c[0]==min(c) and all(c[(i+1)%5] in pa[c[i]] for i in range(5)): C5.add(frozenset(zip(c,c[1:]+c[:1])) and tuple(c) if c[1]<c[4] else None)
C5.discard(None); C5=list(C5); print("5-cycles",len(C5))
nb={v:sorted(pa[v]) for v in range(10)}
# per vertex, per cycle: which pair (as frozenset of neighbours)
uses=[[ (c[i],frozenset((c[i-1],c[(i+1)%5]))) for i in range(5)] for c in C5]
pairs={v:[frozenset(p) for p in itertools.combinations(nb[v],2)] for v in range(10)}
def count(r):
    sols=0
    for H8 in itertools.combinations(range(10),r):
        for ori in itertools.product(range(3),repeat=10):
            sp={v:pairs[v][ori[v]] for v in range(10)}
            ok=True
            for u in uses:
                hits=sum((p!=sp[v]) if v in H8 else (p==sp[v]) for v,p in u)  # H7: special pair =3 ; H8*: special pair =2
                if hits<2: ok=False;break
            if ok: sols+=1
    return sols
# write pet.txt for pet.c: 12 five-cycles x 5 lines "vertex pairindex"
with open("pet.txt","w") as o:
    for u in uses:
        for v,pp in u:
            o.write(f"{v} {pairs[v].index(pp)}\n")
