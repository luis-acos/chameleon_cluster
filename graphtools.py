import numpy as np
import networkx as nx
from tqdm import tqdm
from visualization import *
"""
import pycuda.autoinit
from pycuda.compiler import SourceModule
import pycuda.driver as drv
import pycuda.gpuarray as gpuarray
"""
import metis


def euclidean_distance(a, b):
    return np.linalg.norm(np.array(a) - np.array(b))


def knn_graph(df, k, verbose=False):
    points = [p[1:] for p in df.itertuples()]
    g = nx.Graph()
    for i in range(0, len(points)):
        g.add_node(i)
    if verbose:
        print("Building kNN graph (k = %d)..." % (k))
    iterpoints = tqdm(enumerate(points), total=len(
        points)) if verbose else enumerate(points)
    for i, p in iterpoints:
        distances = list(map(lambda x: euclidean_distance(p, x), points))
        closests = np.argsort(distances)[1:k+1]  # second trough kth closest
        # print(distances[0])
        for c in closests:
            g.add_edge(i, c, weight=1.0 / distances[c], similarity=int(
                1.0 / distances[c] * 1e4))
        g.node[i]['pos'] = p
    g.graph['edge_weight_attr'] = 'similarity'
    return g


def part_graph(graph, k, df=None):
    edgecuts, parts = metis.part_graph(
        graph, 2, objtype='cut', ufactor=250)
    # print(edgecuts)
    for i, p in enumerate(graph.nodes()):
        graph.node[p]['cluster'] = parts[i]
    if df is not None:
        df['cluster'] = nx.get_node_attributes(graph, 'cluster').values()
    return graph


def pre_part_graph(graph, k, df=None, verbose=False):
    if verbose:
        print("Begin clustering...")
    clusters = 0
    for i, p in enumerate(graph.nodes()):
        graph.node[p]['cluster'] = 0
    cnts = {}
    cnts[0] = len(graph.nodes())

    while clusters < k - 1:
        maxc = -1
        maxcnt = 0
        for key, val in cnts.items():
            if val > maxcnt:
                maxcnt = val
                maxc = key
        s_nodes = [n for n in graph.node if graph.node[n]['cluster'] == maxc]
        s_graph = graph.subgraph(s_nodes)
        edgecuts, parts = metis.part_graph(
            s_graph, 2, objtype='cut', ufactor=250)
        new_part_cnt = 0
        for i, p in enumerate(s_graph.nodes()):
            if parts[i] == 1:
                graph.node[p]['cluster'] = clusters + 1
                new_part_cnt = new_part_cnt + 1
        cnts[maxc] = cnts[maxc] - new_part_cnt
        cnts[clusters + 1] = new_part_cnt
        clusters = clusters + 1

    edgecuts, parts = metis.part_graph(graph, k)
    if df is not None:
        df['cluster'] = nx.get_node_attributes(graph, 'cluster').values()
    return graph


def get_cluster(graph, clusters):
    nodes = [n for n in graph.node if graph.node[n]['cluster'] in clusters]
    return nodes


def connecting_edges(partitions, graph):
    cut_set = []
    #print (partitions[0])
    #print (partitions[1])
    for a in partitions[0]:
        for b in partitions[1]:
            if a in graph:
                if b in graph[a]:
                    cut_set.append((a, b))
    print (cut_set)
    return cut_set

"""
def cuda_connecting_edges(partitions, graph):
    block = (len(partitions[0]),1,1)
    grid = (1,1)
    
    mod = source_module(
    __global__ void connecting_edges(float* dest, float* first_cluster, float* second_cluster, int second_cluster_length)
    {
    int set_index = threadId.x;
    int return_index = threadId.x;
    
    for(int second_node_set = 0; second_node_set < second_cluster_length; second_node_set++)
        {
           if(first_cluster[set_index] == second_cluster[second_node_set])
           {
               dest[return_index] = [ first_cluster[first_node_set], second_cluster[second_node_set] ];
           }    
           else 
           {
               dest[return_index][] = -1; 
           }
        }
    }  
    )   
    
    connecting_edges = mod.get_function('connecting_edges')
    
    return_set = [] * len(partitions[0])   
    gpu_return_set = cuda.mem_alloc(return_set.float32)
    
    cluster_i = partitions[0].node
    gpu_cluster_i = gpu_array.to_gpu(cluster_i)
    cluster_j = partitions[1].node
    gpu_cluster_j = gpu_array.to_gpu(cluster_j)
    second_cluster_length = len(cluster_j)
    
    connecting_edges( drv.out(gpu_return_set), drv.in(gpu_cluster_i), drv.in(gpu_cluster_j), driv.in(second_cluster_length), 
                      block, grid)
    
    return_set = [return_set for return_set in a if return_set != -1]
    
    return return_set
"""

def min_cut_bisector(graph):
    graph = graph.copy()
    graph = part_graph(graph, 2)
    partitions = get_cluster(graph, [0]), get_cluster(graph, [1])
    return connecting_edges(partitions, graph)


def get_weights(graph, edges):
    return [graph[edge[0]][edge[1]]['weight'] for edge in edges]


def bisection_weights(graph, cluster):
    cluster = graph.subgraph(cluster)
    edges = min_cut_bisector(cluster)
    weights = get_weights(cluster, edges)
    return weights
