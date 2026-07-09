import torch


def IDFT(time, dim):
    """
    Inverse Discrete Fourier Transform
    Implementation matching models/street_gaussians

    Args:
        time: time value (float or tensor)
        dim: dimension of the Fourier series

    Returns:
        idft: Inverse Discrete Fourier Transform matrix
    """
    if isinstance(time, float):
        time = torch.tensor(time)
    t = time.view(-1, 1).float()
    idft = torch.zeros(t.shape[0], dim)
    indices = torch.arange(dim)
    even_indices = indices[::2]
    odd_indices = indices[1::2]
    idft[:, even_indices] = torch.cos(torch.pi * t * even_indices)
    idft[:, odd_indices] = torch.sin(torch.pi * t * (odd_indices + 1))
    return idft


def get_features_fourier(features_dc, frame, start_frame, end_frame, fourier_dim, fourier_scale=1.0):
    """
    Apply Fourier transform to features

    Args:
        features_dc: original features [N, C, 3]
        frame: current frame
        start_frame: start frame
        end_frame: end frame (-1 for full range)
        fourier_dim: Fourier dimension
        fourier_scale: Fourier scale factor

    Returns:
        features: transformed features [N, 1, 3]
    """
    if end_frame == -1:
        # Enable Fourier for full range - use relative position from start_frame
        normalized_frame = min(1.0, (frame - start_frame) / max(1.0, frame - start_frame + 1))
    else:
        # Use specified range
        normalized_frame = (frame - start_frame) / (end_frame - start_frame)

    time = fourier_scale * normalized_frame
    idft_base = IDFT(time, fourier_dim)[0].to(features_dc.device)
    features_dc = torch.sum(features_dc * idft_base[..., None], dim=1, keepdim=True)  # [N, 1, 3]
    return features_dc