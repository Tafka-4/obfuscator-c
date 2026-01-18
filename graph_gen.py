
import random
from .passes.junk_gen import JunkFactory

class GraphNode:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.edges = [] # List of GraphNode
        self.body = ""

class GraphGenerator:
    def __init__(self, num_nodes=50, layers=5):
        self.num_nodes = num_nodes
        self.layers = layers
        self.nodes = []

    def generate(self):
        # 1. Create Nodes arranged in layers
        layer_buckets = [[] for _ in range(self.layers)]
        
        # Start Node
        start_node = GraphNode(0, "graph_start")
        start_node.body = JunkFactory.generate_body()
        self.nodes.append(start_node)
        layer_buckets[0].append(start_node)
        
        cnt = 1
        for i in range(1, self.layers - 1):
            # Fill intermediate layers
            count_in_layer = self.num_nodes // (self.layers - 2)
            for _ in range(count_in_layer):
                # Add random suffix to avoid collisions if cnt wraps or logic changes
                suffix = random.choices("0123456789ABCDEF", k=4)
                suffix_str = "".join(suffix)
                name = f"graph_node_{cnt:04X}_{suffix_str}"
                node = GraphNode(cnt, name)
                cnt += 1
                node.body = JunkFactory.generate_body()
                self.nodes.append(node)
                layer_buckets[i].append(node)
                
        # End Node (Sink)
        end_node = GraphNode(cnt, "graph_end")
        end_node.body = JunkFactory.generate_body()
        self.nodes.append(end_node)
        layer_buckets[self.layers - 1].append(end_node)
        
        # 2. Connect Layers (Greedy)
        # Ensure every node in layer i connects to at least one in i+1
        # And some random extra connections to i+2, etc. (forward only -> DAG)
        
        for i in range(self.layers - 1):
            current_layer = layer_buckets[i]
            next_layer = layer_buckets[i+1]
            
            for node in current_layer:
                # Must connect to at least one in next layer
                if not next_layer: continue
                target = random.choice(next_layer)
                if target not in node.edges:
                    node.edges.append(target)
                    
                # Chance for extra connections
                if random.random() < 0.3:
                    extra = random.choice(next_layer)
                    if extra not in node.edges:
                        node.edges.append(extra)
                        
                # Chance for jump connection (skip layer)
                if i < self.layers - 2 and random.random() < 0.1:
                     jump_layer = layer_buckets[i+2]
                     if jump_layer:
                         jump = random.choice(jump_layer)
                         if jump not in node.edges:
                             node.edges.append(jump)

    def to_cpp(self):
        # Header
        h_code = "#pragma once\n"
        for node in self.nodes:
            h_code += f"void {node.name}();\n"
        h_code += "void run_graph_wall();\n"
        
        from . import config
        cpp_code = f"""#include "graph_wall.h"
#include "obfuscator_full.hpp"
#include <iostream>
#include <cstdlib>

using namespace {config.NS_NAME};

"""
        # Forward declarations
        for node in self.nodes:
             cpp_code += f"void {node.name}();\n"
             
        cpp_code += "\n"
        
        # Function Definitions
        for node in self.nodes:
            cpp_code += f"void {node.name}() {{\n"
            cpp_code += "    // Organic Junk\n"
            cpp_code += "    " + node.body.replace("\n", "\n    ") + "\n\n"
            
            # Edges logic: shuffle calls to next nodes
            if node.edges:
                # Shuffle order
                targets = list(node.edges)
                random.shuffle(targets)
                # To be "Greedy" and "Massive", let's branch.
                from . import config
                n = len(targets)
                cpp_code += f"    volatile int _decision = {config.NS_NAME}::{config.SBOX_NAME}[rand() % 256] % {n};\n"
                
                for i, target in enumerate(targets):
                     if i == 0:
                         cpp_code += f"    if (_decision == {i}) {target.name}();\n"
                     else:
                         cpp_code += f"    else if (_decision == {i}) {target.name}();\n"
                     
                     # Ensure at least one path is taken?
                     # The above covers 0..n-1.
                     # But valid if/else chain is safer.
         
            cpp_code += "}\n\n"
            
        # Entry point
        cpp_code += """void run_graph_wall() {
    graph_start();
}
"""
        return h_code, cpp_code
