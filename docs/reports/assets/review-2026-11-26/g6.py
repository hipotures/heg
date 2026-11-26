import sys
def parse(s):
    s=s.strip(); d=[ord(c)-63 for c in s]
    if d[0]==63:
        if d[1]==63: n=0; [n:= (n<<6)|x for x in d[2:8]]; p=8
        else:
            n=0
            for x in d[1:4]: n=(n<<6)|x
            p=4
    else: n=d[0]; p=1
    bits=[]
    for x in d[p:]:
        for k in range(5,-1,-1): bits.append((x>>k)&1)
    E=[]; i=0
    for j in range(1,n):
        for a in range(j):
            if bits[i]: E.append((a,j))
            i+=1
    return n,E
def stats(n,E):
    from collections import Counter
    adj=[set() for _ in range(n)]
    for a,b in E: adj[a].add(b); adj[b].add(a)
    deg=Counter(len(x) for x in adj)
    # connectivity + articulation points (iterative Tarjan)
    sys.setrecursionlimit(10000)
    disc=[-1]*n; low=[0]*n; t=[0]; arts=set()
    def dfs(u,p):
        disc[u]=low[u]=t[0]; t[0]+=1; ch=0
        for v in adj[u]:
            if disc[v]<0:
                ch+=1; dfs(v,u); low[u]=min(low[u],low[v])
                if p>=0 and low[v]>=disc[u]: arts.add(u)
            elif v!=p: low[u]=min(low[u],disc[v])
        if p<0 and ch>1: arts.add(u)
    dfs(0,-1)
    conn = all(x>=0 for x in disc)
    # bridges count
    return dict(n=n,m=len(E),deg=dict(sorted(deg.items())),connected=conn,articulation_points=len(arts))
if __name__=="__main__":
    for f in sys.argv[1:]:
        n,E=parse(open(f).read()); print(f.split('/')[-1],stats(n,E))
        with open(f.split('/')[-1]+'.el','w') as o:
            o.write(f"{n} {len(E)}\n"+"".join(f"{a} {b}\n" for a,b in E))
