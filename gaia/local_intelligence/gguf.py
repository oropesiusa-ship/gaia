"""Bounded passive GGUF metadata, no tokenizer code or model implementation imported."""
import struct
from pathlib import Path


def inspect(path):
    with Path(path).open('rb') as stream:
        def read(n):
            if not 0<=n<=16*2**20 or stream.tell()+n>32*2**20:
                raise ValueError('GGUF metadata bounds')
            data=stream.read(n)
            if len(data)!=n: raise ValueError('Truncated GGUF')
            return data
        def number(fmt): return struct.unpack('<'+fmt,read(struct.calcsize(fmt)))[0]
        def string():
            length=number('Q')
            return read(length).decode('utf-8',errors='replace')
        def value(kind, keep=False):
            sizes={0:'B',1:'b',2:'H',3:'h',4:'I',5:'i',6:'f',7:'?',10:'Q',11:'q',12:'d'}
            if kind in sizes: return number(sizes[kind])
            if kind==8: return string()
            if kind==9:
                child,count=number('I'),number('Q')
                if count>1_000_000: raise ValueError('GGUF array bound')
                for _ in range(count): value(child)
                return None
            raise ValueError('Unknown GGUF metadata type')
        if read(4)!=b'GGUF' or number('I') not in (2,3): raise ValueError('Unsupported GGUF')
        tensors,count=number('Q'),number('Q')
        if tensors>1_000_000 or count>20000: raise ValueError('GGUF count bounds')
        result={}
        for _ in range(count):
            key=string(); kind=number('I'); val=value(kind)
            if key in ('general.architecture','general.file_type','general.quantization_version') or key.endswith(('.block_count','.context_length','.embedding_length')):
                result[key]=val
        result['metadata_bytes']=stream.tell()
        return result
