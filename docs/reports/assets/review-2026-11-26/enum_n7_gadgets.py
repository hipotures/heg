# Review follow-up 2026-11-27: exhaustive LABELED enumeration of 7-vertex 3-port gadgets
# (ports 0,1,2 deg 2, internals deg 3, no port-port edges), {C4,C8}-free; prints window types.
import itertools
deg=[2,2,2,3,3,3,3]; n=7
cand=[(a,b) for a,b in itertools.combinations(range(n),2) if not (a<3 and b<3)]
def cycles(adj):
    L=set()
    for s in range(n):
        st=[(s,(s,))]
        while st:
            v,p=st.pop()
            for w in adj[v]:
                if w==s and len(p)>=3: L.add(len(p))
                elif w>s and w not in p: st.append((w,p+(w,)))
    return L
def paths(adj,s,t):
    out=set(); st=[(s,(s,))]
    while st:
        v,p=st.pop()
        for w in adj[v]:
            if w==t: out.add(len(p))
            elif w not in p: st.append((w,p+(w,)))
    return sorted(out)
types={}
for E in itertools.combinations(cand,9):
    d=[0]*n
    for a,b in E: d[a]+=1; d[b]+=1
    if d!=deg: continue
    adj={i:set() for i in range(n)}
    for a,b in E: adj[a].add(b); adj[b].add(a)
    c=cycles(adj)
    if 4 in c or 8 in c: continue
    W=tuple(sorted(tuple(paths(adj,*pq)) for pq in itertools.combinations(range(3),2)))
    types.setdefault(W,E)
for W,E in types.items(): print([(w[0],w[-1],len(w)==w[-1]-w[0]+1) for w in W], E)
