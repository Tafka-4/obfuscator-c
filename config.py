
import os

# Default Configuration
# These can be overridden by arguments in the future
SOURCE_DIRS = ["src"] # Changed to list to support multiple source roots
BUILD_DIR = "build_obfuscated"
OBF_LIB_PATH = os.path.join(BUILD_DIR, "src", "obfuscator_full.hpp")

# Valid extensions for C++ files
VALID_EXTENSIONS = [".cpp", ".c", ".h", ".hpp", ".cc", ".cxx"]

# Dynamic Obfuscation Names
import random
import string

def _prob_random_name(prefix="_"):
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=random.randint(8, 16)))

NS_NAME = _prob_random_name("_N")
CLASS_NAME = _prob_random_name("_C")
METHOD_NAME = _prob_random_name("_d")
SBOX_NAME = _prob_random_name("_S")
MACRO_NAME = _prob_random_name("_M")
