/* Review 2026-11-26. Usage: python3 g6.py X.g6 (writes X.g6.el); gcc -O2 -o cyc cyc.c; ./cyc X.g6.el 34 */
/* Independent exact cycle-length spectrum up to LMAX: for each start s, enumerate simple
   paths in G[{v>=s}] from s, pruned by BFS distance to s inside that subgraph. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int n,m,*deg,**adj,LMAX,s0,*dist,*onp; long long cnt[200]; long long nodes=0;
void dfs(int v,int d){ nodes++;
  for(int i=0;i<deg[v];i++){int w=adj[v][i]; if(w<s0)continue;
    if(w==s0){ if(d+1>=3) cnt[d+1]++; continue;}
    if(onp[w]) continue; if(d+1+dist[w]>LMAX) continue;
    onp[w]=1; dfs(w,d+1); onp[w]=0;}}
int main(int c,char**v){FILE*f=fopen(v[1],"r");LMAX=atoi(v[2]);fscanf(f,"%d %d",&n,&m);
 int *A=malloc(8*m),*B=malloc(8*m);deg=calloc(n,4);
 for(int i=0;i<m;i++){fscanf(f,"%d %d",&A[i],&B[i]);deg[A[i]]++;deg[B[i]]++;}
 adj=malloc(sizeof(int*)*n);int*k=calloc(n,4);for(int i=0;i<n;i++)adj[i]=malloc(4*deg[i]);
 for(int i=0;i<m;i++){adj[A[i]][k[A[i]]++]=B[i];adj[B[i]][k[B[i]]++]=A[i];}
 dist=malloc(4*n);onp=calloc(n,4);int*q=malloc(4*n);
 for(s0=0;s0<n;s0++){for(int i=0;i<n;i++)dist[i]=1<<20;dist[s0]=0;int h=0,t=0;q[t++]=s0;
  while(h<t){int x=q[h++];for(int i=0;i<deg[x];i++){int w=adj[x][i];if(w>=s0&&dist[w]>dist[x]+1){dist[w]=dist[x]+1;q[t++]=w;}}}
  onp[s0]=1;dfs(s0,0);onp[s0]=0;}
 printf("nodes=%lld\nlengths present (count of directed closures /2):",nodes);
 for(int L=3;L<=LMAX;L++) if(cnt[L]) printf(" %d:%lld",L,cnt[L]/2);
 printf("\npow2 check:");for(int L=4;L<=LMAX;L*=2)printf(" C%d=%lld",L,cnt[L]/2);printf("\n");}
