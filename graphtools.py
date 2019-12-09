import numpy as np
import networkx as nx
from tqdm import tqdm
from visualization import *
import pycuda.autoinit
from pycuda.compiler import SourceModule
import pycuda.driver as cuda
import pycuda.gpuarray as gpuarray

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
        g.nodes[i]['pos'] = p
    g.graph['edge_weight_attr'] = 'similarity'
    return g


def part_graph(graph, k, df=None):
    edgecuts, parts = metis.part_graph(
        graph, 2, objtype='cut', ufactor=250)
    # print(edgecuts)
    for i, p in enumerate(graph.nodes()):
        graph.nodes[p]['cluster'] = parts[i]
    if df is not None:
        df['cluster'] = nx.get_node_attributes(graph, 'cluster').values()
    return graph


def pre_part_graph(graph, k, df=None, verbose=False):
    if verbose:
        print("Begin clustering...")
    clusters = 0
    for i, p in enumerate(graph.nodes()):
        graph.nodes[p]['cluster'] = 0
    cnts = {}
    cnts[0] = len(graph.nodes())

    while clusters < k - 1:
        maxc = -1
        maxcnt = 0
        for key, val in cnts.items():
            if val > maxcnt:
                maxcnt = val
                maxc = key
        s_nodes = [n for n in graph.nodes if graph.nodes[n]['cluster'] == maxc]
        s_graph = graph.subgraph(s_nodes)
        edgecuts, parts = metis.part_graph(
            s_graph, 2, objtype='cut', ufactor=250)
        new_part_cnt = 0
        for i, p in enumerate(s_graph.nodes()):
            if parts[i] == 1:
                graph.nodes[p]['cluster'] = clusters + 1
                new_part_cnt = new_part_cnt + 1
        cnts[maxc] = cnts[maxc] - new_part_cnt
        cnts[clusters + 1] = new_part_cnt
        clusters = clusters + 1

    edgecuts, parts = metis.part_graph(graph, k)
    if df is not None:
        df['cluster'] = nx.get_node_attributes(graph, 'cluster').values()
    return graph


def get_cluster(graph, clusters):
    nodes = [n for n in graph.nodes if graph.nodes[n]['cluster'] in clusters]
    return nodes


def connecting_edges(partitions, graph):
    cut_set = []
    #print (partitions[0])
    #print (partitions[1])
    #print('next iteration')
    #adj_graph = nx.to_pandas_adjacency(graph)
    #print(adj_graph)
    for a in partitions[0]:
        for b in partitions[1]:
            if a in graph:
                if b in graph[a]:
                    cut_set.append((a, b))
    #print (cut_set)
    return cut_set


def cuda_connecting_edges(partitions, graph):
    
    mod = SourceModule("""
    __global__ void connecting_edges(float** dest, float* first_cluster, float* second_cluster, float* adj_matrix, 
                                        int second_cluster_length, int matrix_block_size)
    {
        int set_index = threadIdx.x;
        int return_index = threadIdx.x;
        float not_found[1][2] = { {-1.0, -1.0} };       
        float found_pair[1][2];
        
        for(int second_index = 0; second_index < second_cluster_length; second_index++ )
            {
                if(adj_matrix[ (set_index * matrix_block_size) + second_index ] > 0 )
                    {
                        found_pair[0][0] = first_cluster[set_index];
                        found_pair[0][1] = second_cluster[second_index];
                        
                        dest[return_index] = found_pair[0];
                    }
                else 
                        dest[return_index] = not_found[0];
            } 
    }  
    """)   
    
    connecting_edges = mod.get_function('connecting_edges')
    
    return_set = [[]] * (len(partitions[0]) * len(partitions[1]))
    return_set = np.array(return_set)
    return_set = return_set.astype(np.float32)
    gpu_return_set = gpuarray.to_gpu(return_set)

    cluster_i = np.array(partitions[0])
    cluster_i = cluster_i.astype(np.float32)
    gpu_cluster_i = gpuarray.to_gpu(cluster_i)

    cluster_j = np.array(partitions[1])
    cluster_j = cluster_j.astype(np.float32)
    gpu_cluster_j = gpuarray.to_gpu(cluster_j)

    adj_graph = nx.to_pandas_adjacency(graph)

    adj_graph = np.array(adj_graph)
    list_graph = adj_graph.flatten()
    cluster_i = cluster_i.astype(np.float32)
    gpu_list_graph = gpuarray.to_gpu(list_graph)

    gpu_second_cluster_length = np.int32(len(cluster_j))
    gpu_matrix_block_size = np.int32(len(graph))

    connecting_edges(gpu_return_set, gpu_cluster_i, gpu_cluster_j, gpu_list_graph,
                     gpu_second_cluster_length, gpu_matrix_block_size, block=(32, 1, 1), grid=(1, 1))

    pair_set = gpu_return_set.get()
    
    pair_set = [x for x in pair_set if x != (-1, -1)]
    
    return pair_set


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
