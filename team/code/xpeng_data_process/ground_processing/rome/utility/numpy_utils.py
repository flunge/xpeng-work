import numpy as np

def numpy_to_list(data):
    if isinstance(data, dict):
        return {key: numpy_to_list(value) for key, value in data.items()}
    elif isinstance(data, np.ndarray):
        return data.tolist()
    else:
        return data