
import json
import subprocess
import os
from . import config

def get_ast(file_path):
    """
    Generates JSON AST using clang.
    Requires clang in PATH.
    """
    try:
        # -fsyntax-only to speed up, -Xclang -ast-dump=json to get JSON
        # Include src dir for headers - generalized to include all source dirs
        include_flags = []
        for d in config.SOURCE_DIRS:
             include_flags.extend(["-I", d])
             # Also add crypto subdirectory if it exists
             crypto_dir = os.path.join(d, "crypto")
             if os.path.exists(crypto_dir):
                 include_flags.extend(["-I", crypto_dir])
        
        # Must include BUILD_DIR/src because obfuscator_full.hpp will be there
        build_include = os.path.join(config.BUILD_DIR, "src")
        include_flags.extend(["-I", build_include])
        
        # Include build_obfuscated/src/crypto as well for generated files
        build_crypto_include = os.path.join(config.BUILD_DIR, "src", "crypto")
        include_flags.extend(["-I", build_crypto_include])

        cmd = ["clang", "-x", "c++", "-fsyntax-only", "-Xclang", "-ast-dump=json"] + include_flags + ["-std=c++17", file_path]
        # print(f"    [DEBUG] Cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # if not result.stdout:
        #      print(f"    [DEBUG] Empty stdout for {file_path}")
        # else:
        #      print(f"    [DEBUG] Stdout start: {result.stdout[:100]}")
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f"[!] Failed to generate AST for {file_path}: {e}")
        print(f"    STDERR: {e.stderr}")
        return None
    except json.JSONDecodeError:
        print(f"[!] Failed to decode AST JSON for {file_path}")
        return None

def find_nodes(node, kind=None):
    """
    Recursively find nodes of a certain kind.
    """
    matches = []
    if kind is None or node.get("kind") == kind:
        matches.append(node)
    
    for child in node.get("inner", []):
        matches.extend(find_nodes(child, kind))
    return matches

def get_source_range(node):
    """
    Extracts start and end offsets from a node's range.
    """
    rng = node.get("range", {})
    begin = rng.get("begin", {})
    end = rng.get("end", {})
    
    start_offset = begin.get("offset")
    end_offset = end.get("offset")
    
    if end_offset is not None:
         end_offset += end.get("tokLen", 0)
    
    return start_offset, end_offset

def is_in_file(node, target_file):
    """
    Checks if the node belongs to the target file.
    """
    if not target_file: return True

    # Try to find location info
    loc = node.get("loc")
    if not loc:
        rng = node.get("range")
        if rng:
            loc = rng.get("begin")
    
    if not loc: return False # Unsafe if no loc info

    # Check includedFrom first
    if loc.get("includedFrom"):
        return False
    
    node_file = loc.get("file")
    if not node_file:
        return True # Missing file implies main file
    
    # helper to normalize
    def norm(p):
        return os.path.normpath(os.path.abspath(p))
        
    return norm(node_file) == norm(target_file)

def is_safe(name, decl_node, file_path=""):
    if not name: return False
    if len(name) < 2: return False 
    if name == "main": return False
    if name.startswith("_"): return False 
    if name in ["argc", "argv"]: return False
    
    if name.startswith("std::"): return False
    if name.startswith("in6addr_"): return False
    if name.startswith("operator"): return False 
    if name.startswith("~"): return False 
    if name == "is_prime": return False 

    # Expanded Blacklist (MacOS/BSD/POSIX)
    SYSTEM_BLACKLIST = {
        "signal", "raise", "kill", "exit", "abort", "atexit", "_exit",
        "read", "write", "open", "close", "lseek", "stat", "fstat",
        "socket", "bind", "listen", "accept", "connect", "send", "recv", "recvmsg", "sendmsg", "socketpair",
        "setsockopt", "getsockopt", "getpeername", "getsockname",
        "sendto", "recvfrom", "shutdown", "select", "poll", "pselect",
        "fork", "execv", "execve", "execvp", "wait", "waitpid", "pipe",
        "memset", "memcpy", "memmove", "strcpy", "strncpy", "strcat", "strlen", "strcmp", "strncmp",
        "printf", "fprintf", "sprintf", "snprintf", "scanf", "sscanf", "perror", "puts", "fputs", "putchar", "getchar",
        "malloc", "free", "calloc", "realloc",
        "htons", "htonl", "ntohs", "ntohl", "inet_addr", "inet_ntoa", "inet_ntop", "inet_pton",
        "gethostname", "gethostbyname", "getaddrinfo", "freeaddrinfo", "gai_strerror",
        "access", "alarm", "chdir", "chown", "dup", "dup2", "fpathconf", "getcwd",
        "getegid", "geteuid", "getgid", "getgroups", "getlogin", "getpgrp", "getpid", "getppid", "getuid",
        "isatty", "link", "pathconf", "pause", "rmdir", "setgid", "setpgid", "setsid", "setuid",
        "sleep", "sysconf", "tcgetpgrp", "tcsetpgrp", "ttyname", "unlink",
        "usleep", "ualarm", "vfork", "truncate", "ftruncate", "sync", "fsync",
        "chmod", "fchmod", "mkdir", "rename", "time", "ctime", "gettimeofday",
        "random", "srandom", "rand", "srand", "atoi", "atof", "atol", "strtol",
        "bzero", "bcopy", "index", "rindex", "strcasecmp", "strncasecmp",
        "sendfile", "pfctlinput", "connectx", "disconnectx",
        "setipv4sourcefilter", "getipv4sourcefilter", "setsourcefilter", "getsourcefilter",
        "inet6_option_space", "inet6_option_init", "inet6_option_append", "inet6_option_alloc",
        "inet6_option_next", "inet6_option_find", "inet6_rthdr_space", "inet6_rthdr_init",
        "bindresvport", "bindresvport_sa", "iruserok", "ruserok", "rcmd", "rcmd_af", "rresvport",
        # C++ Container methods
        "size", "empty", "clear", "resize", "reserve", "push_back", "pop_back", "push_front", "pop_front", "assign",
        "insert", "erase", "begin", "end", "rbegin", "rend", "cbegin", "cend", "front", "back", "at",
        "data", "c_str", "length", "substr", "append", "compare", "find", "rfind", "replace",
        "to_string", "stoi", "stol", "stoul", "stoll", "stoull", "stof", "stod", "stold",
        "make_shared", "make_unique", "move", "forward", "swap",
        "max", "min", "abs", "div", "pair", "make_pair", "first", "second",
        "sort", "reverse", "copy", "transform", "accumulate", "unique", "find_if", "count", "count_if",
        "npos", "getline",
        # IOStream
        "cout", "cin", "cerr", "clog", "endl", "ends", "flush", "hex", "dec", "oct", "fixed", "scientific", "left", "right",
        # Network Struct Fields
        "sin_family", "sin_port", "sin_addr", "sin_zero", "s_addr",
        "sa_family", "sa_data",
        "ai_flags", "ai_family", "ai_socktype", "ai_protocol", "ai_addrlen", "ai_addr", "ai_canonname", "ai_next",
        "h_name", "h_aliases", "h_addrtype", "h_length", "h_addr_list", "h_addr",
        "tm_sec", "tm_min", "tm_hour", "tm_mday", "tm_mon", "tm_year", "tm_wday", "tm_yday", "tm_isdst",
        "tv_sec", "tv_usec",
        # Missing System Structs/Methods
        "sockaddr", "sockaddr_in", "in_addr",
        "find_first_not_of", "find_last_not_of", "rdbuf", "str",
        # C++ Standard Types
        "string", "wstring", "vector", "list", "map", "set", "deque", "stack", "queue", "priority_queue",
        "multimap", "multiset", "unordered_map", "unordered_set", "pair", "tuple",
        "unique_ptr", "shared_ptr", "weak_ptr", "auto_ptr",
        "stringstream", "istringstream", "ostringstream",
        "ifstream", "ofstream", "fstream", "filebuf",
        "istream", "ostream", "iostream", "streambuf",
        "exception", "runtime_error", "logic_error", "out_of_range", "invalid_argument",
        "mutex", "thread", "condition_variable", "future", "promise",
        "function", "bind", "ref", "cref",
        "allocator", "iterator", "const_iterator", "reverse_iterator", "const_reverse_iterator",
        "char_traits", "complex", "valarray",
        "sync_with_stdio",
        "setfill", "setw", "setprecision",
        "setvbuf", "stdout", "stdin", "stderr", "_IONBF", "_IOLBF", "_IOFBF"
    }
    if name in SYSTEM_BLACKLIST: return False
    
    # Check Source Location!
    loc = decl_node.get("loc", {})
    presumed_file = loc.get("presumedFile", loc.get("file", ""))
    
    if not presumed_file: 
        presumed_file = file_path
        
    if not presumed_file: return False # Still unknown -> Unsafe
    
    abs_presumed = os.path.abspath(presumed_file)
    
    # Safe if it's within ANY of the SOURCE_DIRS or BUILD_DIR or is a temp file
    is_in_source = False
    allowed_dirs = config.SOURCE_DIRS + [config.BUILD_DIR]
    
    for d in allowed_dirs:
        abs_src = os.path.abspath(d)
        if abs_presumed.startswith(abs_src):
            is_in_source = True
            break
            
    is_temp = "/tmp/" in abs_presumed or "/var/folders/" in abs_presumed or "tmp" in abs_presumed
    
    if not is_in_source and not is_temp:
        # print(f"    [DEBUG] REJECTED {name}: Not in source/temp ({abs_presumed})")
        return False
        
    return True
