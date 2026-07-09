#include <ATen/TensorUtils.h>
#include <ATen/core/Tensor.h>
#include <c10/cuda/CUDAGuard.h> // for DEVICE_GUARD
#include <tuple>

#include <ATen/Functions.h>
#include <ATen/NativeFunctions.h>

#include "Common.h"     // where all the macros are defined
#include "Ops.h"        // a collection of all gsplat operators
#include "Projection.h" // where the launch function is declared
#include "Cameras.h"

namespace xpeng_raster {

std::tuple<at::Tensor, at::Tensor> projection_ewa_simple_fwd(
    const at::Tensor means,  // [..., C, N, 3]
    const at::Tensor covars, // [..., C, N, 3, 3]
    const at::Tensor Ks,     // [..., C, 3, 3]
    const uint32_t width,
    const uint32_t height,
    const CameraModelType camera_model
) { TORCH_CHECK(false, "projection_ewa_simple_fwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(), at::Tensor()); }

std::tuple<at::Tensor, at::Tensor> projection_ewa_simple_bwd(
    const at::Tensor means,  // [..., C, N, 3]
    const at::Tensor covars, // [..., C, N, 3, 3]
    const at::Tensor Ks,     // [..., C, 3, 3]
    const uint32_t width,
    const uint32_t height,
    const CameraModelType camera_model,
    const at::Tensor v_means2d, // [..., C, N, 2]
    const at::Tensor v_covars2d // [..., C, N, 2, 2]
) { TORCH_CHECK(false, "projection_ewa_simple_bwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(), at::Tensor()); }

std::tuple<
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor>
projection_ewa_3dgs_fused_fwd(
    const at::Tensor means,                // [..., N, 3]
    const at::optional<at::Tensor> covars, // [..., N, 6] optional
    const at::optional<at::Tensor> quats,  // [..., N, 4] optional
    const at::optional<at::Tensor> scales, // [..., N, 3] optional
    const at::optional<at::Tensor> opacities, // [..., N] optional
    const at::Tensor viewmats,             // [..., C, 4, 4]
    const at::Tensor Ks,                   // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    const float eps2d,
    const float near_plane,
    const at::Tensor far_plane,
    const float radius_clip,
    const bool calc_compensations,
    const CameraModelType camera_model
) {
    DEVICE_GUARD(means);
    CHECK_INPUT(means);
    if (covars.has_value()) {
        CHECK_INPUT(covars.value());
    } else {
        assert(quats.has_value() && scales.has_value());
        CHECK_INPUT(quats.value());
        CHECK_INPUT(scales.value());
    }
    CHECK_INPUT(viewmats);
    CHECK_INPUT(Ks);

    auto opt = means.options();
    at::DimVector batch_dims(means.sizes().slice(0, means.dim() - 2));
    uint32_t N = means.size(-2);    // number of gaussians
    uint32_t C = viewmats.size(-3); // number of cameras

    at::DimVector radii_shape(batch_dims);
    radii_shape.append({C, N, 2});
    at::Tensor radii = at::empty(radii_shape, opt.dtype(at::kInt));
    at::DimVector means2d_shape(batch_dims);
    means2d_shape.append({C, N, 2});
    at::Tensor means2d = at::empty(means2d_shape, opt);
    at::DimVector depths_shape(batch_dims);
    depths_shape.append({C, N});
    at::Tensor depths = at::empty(depths_shape, opt);
    at::DimVector conics_shape(batch_dims);
    conics_shape.append({C, N, 3});
    at::Tensor conics = at::empty(conics_shape, opt);
    at::Tensor compensations;
    if (calc_compensations) {
        at::DimVector compensations_shape(batch_dims);
        compensations_shape.append({C, N});
        compensations = at::zeros(compensations_shape, opt);
    }

    launch_projection_ewa_3dgs_fused_fwd_kernel(
        // inputs
        means,
        covars,
        quats,
        scales,
        opacities,
        viewmats,
        Ks,
        image_width,
        image_height,
        eps2d,
        near_plane,
        far_plane,
        radius_clip,
        camera_model,
        // outputs
        radii,
        means2d,
        depths,
        conics,
        calc_compensations ? at::optional<at::Tensor>(compensations)
                           : c10::nullopt
    );
    return std::make_tuple(radii, means2d, depths, conics, compensations);
}

std::tuple<at::Tensor, at::Tensor, at::Tensor, at::Tensor, at::Tensor>
projection_ewa_3dgs_fused_bwd(
    // fwd inputs
    const at::Tensor means,                // [..., N, 3]
    const at::optional<at::Tensor> covars, // [..., N, 6] optional
    const at::optional<at::Tensor> quats,  // [..., N, 4] optional
    const at::optional<at::Tensor> scales, // [..., N, 3] optional
    const at::Tensor viewmats,             // [..., C, 4, 4]
    const at::Tensor Ks,                   // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    const float eps2d,
    const CameraModelType camera_model,
    // fwd outputs
    const at::Tensor radii,                       // [..., C, N, 2]
    const at::Tensor conics,                      // [..., C, N, 3]
    const at::optional<at::Tensor> compensations, // [..., C, N] optional
    // grad outputs
    const at::Tensor v_means2d,                     // [..., C, N, 2]
    const at::Tensor v_depths,                      // [..., C, N]
    const at::Tensor v_conics,                      // [..., C, N, 3]
    const at::optional<at::Tensor> v_compensations, // [..., C, N] optional
    const bool viewmats_requires_grad
) {
    DEVICE_GUARD(means);
    CHECK_INPUT(means);
    if (covars.has_value()) {
        CHECK_INPUT(covars.value());
    } else {
        assert(quats.has_value() && scales.has_value());
        CHECK_INPUT(quats.value());
        CHECK_INPUT(scales.value());
    }
    CHECK_INPUT(viewmats);
    CHECK_INPUT(Ks);
    CHECK_INPUT(radii);
    CHECK_INPUT(conics);
    CHECK_INPUT(v_means2d);
    CHECK_INPUT(v_depths);
    CHECK_INPUT(v_conics);
    if (compensations.has_value()) {
        CHECK_INPUT(compensations.value());
    }
    if (v_compensations.has_value()) {
        CHECK_INPUT(v_compensations.value());
        assert(compensations.has_value());
    }

    at::Tensor v_means = at::zeros_like(means);
    at::Tensor v_covars, v_quats, v_scales; // optional
    if (covars.has_value()) {
        v_covars = at::zeros_like(covars.value());
    } else {
        v_quats = at::zeros_like(quats.value());
        v_scales = at::zeros_like(scales.value());
    }
    at::Tensor v_viewmats;
    if (viewmats_requires_grad) {
        v_viewmats = at::zeros_like(viewmats);
    }

    launch_projection_ewa_3dgs_fused_bwd_kernel(
        // inputs
        means,
        covars,
        quats,
        scales,
        viewmats,
        Ks,
        image_width,
        image_height,
        eps2d,
        camera_model,
        radii,
        conics,
        compensations,
        v_means2d,
        v_depths,
        v_conics,
        v_compensations,
        viewmats_requires_grad,
        // outputs
        v_means,
        v_covars,
        v_quats,
        v_scales,
        v_viewmats
    );

    return std::make_tuple(v_means, v_covars, v_quats, v_scales, v_viewmats);
}

std::tuple<
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor>
projection_ewa_3dgs_packed_fwd(
    const at::Tensor means,                // [..., N, 3]
    const at::optional<at::Tensor> covars, // [..., N, 6] optional
    const at::optional<at::Tensor> quats,  // [..., N, 4] optional
    const at::optional<at::Tensor> scales, // [..., N, 3] optional
    const at::optional<at::Tensor> opacities, // [..., N] optional
    const at::Tensor viewmats,             // [..., C, 4, 4]
    const at::Tensor Ks,                   // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    const float eps2d,
    const float near_plane,
    const at::Tensor far_plane,
    const float radius_clip,
    const bool calc_compensations,
    const CameraModelType camera_model
){ TORCH_CHECK(false, "projection_ewa_3dgs_packed_fwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor()); }

std::tuple<at::Tensor, at::Tensor, at::Tensor, at::Tensor, at::Tensor>
projection_ewa_3dgs_packed_bwd(
    // fwd inputs
    const at::Tensor means,                // [..., N, 3]
    const at::optional<at::Tensor> covars, // [..., N, 6]
    const at::optional<at::Tensor> quats,  // [..., N, 4]
    const at::optional<at::Tensor> scales, // [..., N, 3]
    const at::Tensor viewmats,             // [..., C, 4, 4]
    const at::Tensor Ks,                   // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    const float eps2d,
    const CameraModelType camera_model,
    // fwd outputs
    const at::Tensor batch_ids,                     // [nnz]
    const at::Tensor camera_ids,                    // [nnz]
    const at::Tensor gaussian_ids,                  // [nnz]
    const at::Tensor conics,                        // [nnz, 3]
    const at::optional<at::Tensor> compensations,   // [nnz] optional
    // grad outputs
    const at::Tensor v_means2d,                     // [nnz, 2]
    const at::Tensor v_depths,                      // [nnz]
    const at::Tensor v_conics,                      // [nnz, 3]
    const at::optional<at::Tensor> v_compensations, // [nnz] optional
    const bool viewmats_requires_grad,
    const bool sparse_grad
){ TORCH_CHECK(false, "projection_ewa_3dgs_packed_bwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor()); }

std::tuple<
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor>
projection_2dgs_fused_fwd(
    const at::Tensor means,    // [..., N, 3]
    const at::Tensor quats,    // [..., N, 4]
    const at::Tensor scales,   // [..., N, 3]
    const at::Tensor viewmats, // [..., C, 4, 4]
    const at::Tensor Ks,       // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    const float eps2d,
    const float near_plane,
    const at::Tensor far_plane,
    const float radius_clip
) { TORCH_CHECK(false, "projection_2dgs_fused_fwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor()); }

std::tuple<at::Tensor, at::Tensor, at::Tensor, at::Tensor>
projection_2dgs_fused_bwd(
    // fwd inputs
    const at::Tensor means,    // [..., N, 3]
    const at::Tensor quats,    // [..., N, 4]
    const at::Tensor scales,   // [..., N, 3]
    const at::Tensor viewmats, // [..., C, 4, 4]
    const at::Tensor Ks,       // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    // fwd outputs
    const at::Tensor radii,          // [..., C, N, 2]
    const at::Tensor ray_transforms, // [..., C, N, 3, 3]
    // grad outputs
    const at::Tensor v_means2d,        // [..., C, N, 2]
    const at::Tensor v_depths,         // [..., C, N]
    const at::Tensor v_normals,        // [..., C, N, 3]
    const at::Tensor v_ray_transforms, // [..., C, N, 3, 3]
    const bool viewmats_requires_grad
){ TORCH_CHECK(false, "projection_2dgs_fused_bwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor()); }

std::tuple<
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor>
projection_2dgs_packed_fwd(
    const at::Tensor means,    // [..., N, 3]
    const at::Tensor quats,    // [..., N, 4]
    const at::Tensor scales,   // [..., N, 3]
    const at::Tensor viewmats, // [..., C, 4, 4]
    const at::Tensor Ks,       // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    const float near_plane,
    const at::Tensor far_plane,
    const float radius_clip
){ TORCH_CHECK(false, "projection_2dgs_packed_fwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor(),at::Tensor()); }

std::tuple<at::Tensor, at::Tensor, at::Tensor, at::Tensor>
projection_2dgs_packed_bwd(
    // fwd inputs
    const at::Tensor means,    // [..., N, 3]
    const at::Tensor quats,    // [..., N, 4]
    const at::Tensor scales,   // [..., N, 3]
    const at::Tensor viewmats, // [..., C, 4, 4]
    const at::Tensor Ks,       // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    // fwd outputs
    const at::Tensor batch_ids,      // [nnz]
    const at::Tensor camera_ids,     // [nnz]
    const at::Tensor gaussian_ids,   // [nnz]
    const at::Tensor ray_transforms, // [nnz, 3, 3]
    // grad outputs
    const at::Tensor v_means2d,        // [nnz, 2]
    const at::Tensor v_depths,         // [nnz]
    const at::Tensor v_ray_transforms, // [nnz, 3, 3]
    const at::Tensor v_normals,        // [nnz, 3]
    const bool viewmats_requires_grad,
    const bool sparse_grad
){ TORCH_CHECK(false, "projection_2dgs_packed_bwd is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor()); }

std::tuple<
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor,
    at::Tensor>
projection_ut_3dgs_fused(
    const at::Tensor means,                   // [..., N, 3]
    const at::Tensor quats,                   // [..., N, 4]
    const at::Tensor scales,                  // [..., N, 3]
    const at::optional<at::Tensor> opacities, // [..., N] optional
    const at::Tensor viewmats0,               // [..., C, 4, 4]
    const at::optional<at::Tensor> viewmats1, // [..., C, 4, 4] optional for rolling shutter
    const at::Tensor Ks,                      // [..., C, 3, 3]
    const uint32_t image_width,
    const uint32_t image_height,
    const float eps2d,
    const float near_plane,
    const at::Tensor far_plane,
    const float radius_clip,
    const bool calc_compensations,
    const CameraModelType camera_model,
    // uncented transform
    const UnscentedTransformParameters ut_params,
    ShutterType rs_type,
    const at::optional<at::Tensor> radial_coeffs,     // [..., C, 6] or [..., C, 4] optional
    const at::optional<at::Tensor> tangential_coeffs, // [..., C, 2] optional
    const at::optional<at::Tensor> thin_prism_coeffs,  // [..., C, 4] optional
    const FThetaCameraDistortionParameters ftheta_coeffs // shared parameters for all cameras
){ TORCH_CHECK(false, "projection_ut_3dgs_fused is not supported in xpeng_raster"); return std::make_tuple(at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor(), at::Tensor()); }

} // namespace xpeng_raster
