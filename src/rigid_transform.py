from typing import Tuple

import numpy as np
from sklearn.neighbors import KDTree

from .transformation import Transformation


def solver_point_to_point(
    scan: np.ndarray[np.float64], ref: np.ndarray[np.float64]
) -> Transformation:
    """
    Computes the least-squares best-fit transform that maps corresponding points data to ref.
    """

    data_barycenter = scan.mean(axis=0)
    ref_barycenter = ref.mean(axis=0)
    covariance_matrix = (scan - data_barycenter).T.dot(ref - ref_barycenter)
    u, sigma, v = np.linalg.svd(covariance_matrix)
    rotation = v.T @ u.T

    # ensuring that we have a direct rotation (determinant equal to 1 and not -1)
    if np.linalg.det(rotation) < 0:
        u_transpose = u.T
        u_transpose[-1] *= -1
        rotation = v.T @ u_transpose

    translation = ref_barycenter - rotation.dot(data_barycenter)

    return Transformation(rotation, translation)


def compute_point_to_point_error(
    scan: np.ndarray[np.float64],
    ref: np.ndarray[np.float64],
    transformation: Transformation,
) -> Tuple[float, np.ndarray[np.float64]]:
    """
    Computes the RMS error between a reference point cloud and data that went through the rigid transformation described
    by the rotation and the translation.
    """
    transformed_data = transformation.transform(scan)
    neighbors = KDTree(ref).query(transformed_data, return_distance=False).squeeze()
    return (
        np.sqrt(
            np.sum(
                (transformed_data - ref[neighbors]) ** 2,
                axis=0,
            ).mean()
        ),
        transformed_data,
    )
