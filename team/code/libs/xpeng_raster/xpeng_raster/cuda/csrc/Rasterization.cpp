#include <ATen/TensorUtils.h>
#include <ATen/core/Tensor.h>
#include <c10/cuda/CUDAGuard.h> // for DEVICE_GUARD
#include <tuple>

#include <ATen/Functions.h>
#include <ATen/NativeFunctions.h>

#include "Common.h"
#include "Ops.h"
#include "Rasterization.h"
#include "Cameras.h"

namespace xpeng_raster {

////////////////////////////////////////////////////
// 3DGS
////////////////////////////////////////////////////

std::tuple<at::Tensor, at::Tensor, at::Tensor> rasterize_to_pixels_3dgs_fwd(
    // Gaussian parameters
    const at::Tensor means2d,   // [..., N, 2] or [nnz, 2]
    const at::Tensor conics,    // [..., N, 3] or [nnz, 3]
    const at::Tensor colors,    // [..., N, channels] or [nnz, channels]
    const at::Tensor opacities, // [..., N]  or [nnz]
    const at::optional<at::Tensor> backgrounds, // [..., channels]
    const at::optional<at::Tensor> masks,       // [..., tile_height, tile_width]
    // image size
    const uint32_t image_width,
    const uint32_t image_height,
    const uint32_t tile_size,
    // intersections
    const at::Tensor tile_offsets, // [..., tile_height, tile_width]
    const at::Tensor flatten_ids   // [n_isects]
) {
    DEVICE_GUARD(means2d);
    CHECK_INPUT(means2d);
    CHECK_INPUT(conics);
    CHECK_INPUT(colors);
    CHECK_INPUT(opacities);
    CHECK_INPUT(tile_offsets);
    CHECK_INPUT(flatten_ids);
    if (backgrounds.has_value()) {
        CHECK_INPUT(backgrounds.value());
    }
    if (masks.has_value()) {
        CHECK_INPUT(masks.value());
    }

    auto opt = means2d.options();
    at::DimVector image_dims(tile_offsets.sizes().slice(0, tile_offsets.dim() - 2));
    uint32_t channels = colors.size(-1);
    TORCH_CHECK(channels == 3, "xpeng_raster only supports RGB (3 channels)");

    at::DimVector renders_dims(image_dims);
    renders_dims.append({image_height, image_width, channels});
    at::Tensor renders = at::empty(renders_dims, opt);

    at::DimVector alphas_dims(image_dims);
    alphas_dims.append({image_height, image_width, 1});
    at::Tensor alphas = at::empty(alphas_dims, opt);

    at::DimVector last_ids_dims(image_dims);
    last_ids_dims.append({image_height, image_width});
    at::Tensor last_ids = at::empty(last_ids_dims, opt.dtype(at::kInt));

#define __LAUNCH_KERNEL__(N)                                                   \
    case N:                                                                    \
        launch_rasterize_to_pixels_3dgs_fwd_kernel<N>(                         \
            means2d,                                                           \
            conics,                                                            \
            colors,                                                            \
            opacities,                                                         \
            backgrounds,                                                       \
            masks,                                                             \
            image_width,                                                       \
            image_height,                                                      \
            tile_size,                                                         \
            tile_offsets,                                                      \
            flatten_ids,                                                       \
            renders,                                                           \
            alphas,                                                            \
            last_ids                                                           \
        );                                                                     \
        break;

    // TODO: an optimization can be done by passing the actual number of
    // channels into the kernel functions and avoid necessary global memory
    // writes. This requires moving the channel padding from python to C side.
    switch (channels) {
        __LAUNCH_KERNEL__(3)
    default:
        AT_ERROR("Unsupported number of channels: ", channels);
    }
#undef __LAUNCH_KERNEL__

    return std::make_tuple(renders, alphas, last_ids);
}

std::tuple<at::Tensor, at::Tensor, at::Tensor, at::Tensor, at::Tensor>
rasterize_to_pixels_3dgs_bwd(
    // Gaussian parameters
    const at::Tensor means2d,                   // [..., N, 2] or [nnz, 2]
    const at::Tensor conics,                    // [..., N, 3] or [nnz, 3]
    const at::Tensor colors,                    // [..., N, channels] or [nnz, channels]
    const at::Tensor opacities,                 // [..., N] or [nnz]
    const at::optional<at::Tensor> backgrounds, // [..., channels]
    const at::optional<at::Tensor> masks,       // [..., tile_height, tile_width]
    // image size
    const uint32_t image_width,
    const uint32_t image_height,
    const uint32_t tile_size,
    // intersections
    const at::Tensor tile_offsets, // [..., tile_height, tile_width]
    const at::Tensor flatten_ids,  // [n_isects]
    // forward outputs
    const at::Tensor render_alphas, // [..., image_height, image_width, 1]
    const at::Tensor last_ids,      // [..., image_height, image_width]
    // gradients of outputs
    const at::Tensor v_render_colors, // [..., image_height, image_width, channels]
    const at::Tensor v_render_alphas, // [..., image_height, image_width, 1]
    // options
    bool absgrad
) {
    TORCH_CHECK(false, "rasterize_to_pixels_3dgs_bwd is not supported in xpeng_raster");
    return std::make_tuple(at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor());
}

std::tuple<at::Tensor, at::Tensor> rasterize_to_indices_3dgs(
    const uint32_t range_start,
    const uint32_t range_end,        // iteration steps
    const at::Tensor transmittances, // [..., image_height, image_width]
    // Gaussian parameters
    const at::Tensor means2d,   // [..., N, 2]
    const at::Tensor conics,    // [..., N, 3]
    const at::Tensor opacities, // [..., N]
    // image size
    const uint32_t image_width,
    const uint32_t image_height,
    const uint32_t tile_size,
    // intersections
    const at::Tensor tile_offsets, // [..., tile_height, tile_width]
    const at::Tensor flatten_ids   // [n_isects]
) {
    TORCH_CHECK(false, "rasterize_to_indices_3dgs is not supported in xpeng_raster");
    return std::make_tuple(at::Tensor(), at::Tensor());
}

////////////////////////////////////////////////////
// 3DGS (from world)
////////////////////////////////////////////////////

std::tuple<at::Tensor, at::Tensor, at::Tensor> rasterize_to_pixels_from_world_3dgs_fwd(
    // Gaussian parameters
    const at::Tensor means,     // [..., N, 3]
    const at::Tensor quats,     // [..., N, 4]
    const at::Tensor scales,    // [..., N, 3]
    const at::Tensor colors,    // [..., C, N, channels] or [nnz, channels]
    const at::Tensor opacities, // [..., C, N] or [nnz]
    const at::optional<at::Tensor> backgrounds, // [..., C, channels]
    const at::optional<at::Tensor> masks,       // [..., C, tile_height, tile_width]
    // image size
    const uint32_t image_width,
    const uint32_t image_height,
    const uint32_t tile_size,
    // camera
    const at::Tensor viewmats0,               // [..., C, 4, 4]
    const at::optional<at::Tensor> viewmats1, // [..., C, 4, 4] optional for rolling shutter
    const at::Tensor Ks,                      // [..., C, 3, 3]
    const CameraModelType camera_model,
    // uncented transform
    const UnscentedTransformParameters ut_params,
    ShutterType rs_type,
    const at::optional<at::Tensor> radial_coeffs,     // [..., C, 6] or [..., C, 4] optional
    const at::optional<at::Tensor> tangential_coeffs, // [..., C, 2] optional
    const at::optional<at::Tensor> thin_prism_coeffs, // [..., C, 4] optional
    const FThetaCameraDistortionParameters ftheta_coeffs, // shared parameters for all cameras
    // intersections
    const at::Tensor tile_offsets, // [..., C, tile_height, tile_width]
    const at::Tensor flatten_ids   // [n_isects]
) {
    TORCH_CHECK(false, "rasterize_to_pixels_from_world_3dgs_fwd is not supported in xpeng_raster");
    // unreachable
    return std::make_tuple(at::Tensor(), at::Tensor(), at::Tensor());
};


std::tuple<at::Tensor, at::Tensor, at::Tensor, at::Tensor, at::Tensor>
rasterize_to_pixels_from_world_3dgs_bwd(
    // Gaussian parameters
    const at::Tensor means,  // [..., N, 3]
    const at::Tensor quats,  // [..., N, 4]
    const at::Tensor scales, // [..., N, 3]
    const at::Tensor colors,                    // [..., C, N, 3] or [nnz, 3]
    const at::Tensor opacities,                 // [..., C, N] or [nnz]
    const at::optional<at::Tensor> backgrounds, // [..., C, 3]
    const at::optional<at::Tensor> masks,       // [..., C, tile_height, tile_width]
    // image size
    const uint32_t image_width,
    const uint32_t image_height,
    const uint32_t tile_size,
    // camera
    const at::Tensor viewmats0,               // [..., C, 4, 4]
    const at::optional<at::Tensor> viewmats1, // [..., C, 4, 4] optional for rolling shutter
    const at::Tensor Ks,                      // [..., C, 3, 3]
    const CameraModelType camera_model,
    // uncented transform
    const UnscentedTransformParameters ut_params,
    ShutterType rs_type,
    const at::optional<at::Tensor> radial_coeffs,     // [..., C, 6] or [..., C, 4] optional
    const at::optional<at::Tensor> tangential_coeffs, // [..., C, 2] optional
    const at::optional<at::Tensor> thin_prism_coeffs, // [..., C, 4] optional
    const FThetaCameraDistortionParameters ftheta_coeffs, // shared parameters for all cameras
    // intersections
    const at::Tensor tile_offsets, // [..., C, tile_height, tile_width]
    const at::Tensor flatten_ids,  // [n_isects]
    // forward outputs
    const at::Tensor render_alphas, // [..., C, image_height, image_width, 1]
    const at::Tensor last_ids,      // [..., C, image_height, image_width]
    // gradients of outputs
    const at::Tensor v_render_colors, // [..., C, image_height, image_width, 3]
    const at::Tensor v_render_alphas // [..., C, image_height, image_width, 1]
) {
    TORCH_CHECK(false, "rasterize_to_pixels_from_world_3dgs_bwd is not supported in xpeng_raster");
    // unreachable
    return std::make_tuple(at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor());
}

} // namespace xpeng_raster
