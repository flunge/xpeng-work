from setuptools import setup
from setuptools import find_packages
from torch.utils.cpp_extension import BuildExtension, CUDAExtension
import os

this_dir = os.path.dirname(os.path.abspath(__file__))

sources = [
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'ext.cpp'),
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'csrc', 'Projection.cpp'),
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'csrc', 'Rasterization.cpp'),
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'csrc', 'Intersect.cpp'),
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'csrc', 'ProjectionEWA3DGSFused.cu'),
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'csrc', 'RasterizeToPixels3DGSFwd.cu'),
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'csrc', 'IntersectTile.cu'),
]

include_dirs = [
    os.path.join(this_dir, 'xpeng_raster', 'cuda', 'include'),
]

use_fast_math = os.environ.get('XPR_FAST_MATH', '1') == '1'
nvcc_args = ['-O3', '-lineinfo']
if use_fast_math:
    nvcc_args += ['-use_fast_math']
extra_compile_args = {
    'cxx': ['-O3'],
    'nvcc': nvcc_args,
}

setup(
    name='xpeng_raster',
    version='0.1.0',
    packages=find_packages(),
    ext_modules=[
        CUDAExtension(
            name='xpeng_raster._C',
            sources=sources,
            include_dirs=include_dirs,
            extra_compile_args=extra_compile_args,
        )
    ],
    cmdclass={'build_ext': BuildExtension},
)
