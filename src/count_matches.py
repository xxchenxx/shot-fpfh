from typing import List, Dict, Tuple

import numpy as np
from scipy.spatial.transform import Rotation


def quaternion_to_rotation_matrix(quaternion: List[float]) -> np.ndarray:
    """
    Converts a quaternion into a full three-dimensional rotation matrix.
    """
    q3, q0, q1, q2 = quaternion
    return Rotation.from_quat([q0, q1, q2, q3]).as_matrix().squeeze()


def read_conf_file(file_path: str) -> Dict[str, Tuple[np.ndarray, np.ndarray]]:
    """
    Reads a .conf file from the Stanford 3D Scanning Repository to output the (translation, rotation) for each ply file.
    """
    with open(file_path, "r") as file:
        transformations = {
            line_values[1].replace(".ply", ""): (
                quaternion_to_rotation_matrix([float(val) for val in line_values[5:]]),
                np.array([float(val) for val in line_values[2:5]]),
            )
            for line in file.readlines()
            if (line_values := line.split(" "))[0] == "bmesh"
        }
    return transformations


def get_resulting_transform(
    file_name: str, ref_file_name: str, conf: Dict[str, Tuple[np.ndarray, np.ndarray]]
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Outputs the rotation and translation that send the data corresponding to file_name onto the data corresponding to
    ref_file_name using a config that contains rotations and translations to send them to a common coordinate system.
    """
    rotation, translation = conf[file_name.split("/")[-1].replace(".ply", "")]
    rotation_ref, translation_ref = conf[
        ref_file_name.split("/")[-1].replace(".ply", "")
    ]

    return rotation_ref.T @ rotation, rotation_ref.T @ (translation - translation_ref)


def count_correct_matches(
    data: np.ndarray, ref: np.ndarray, rotation: np.ndarray, translation: np.ndarray
) -> int:
    """
    Counts the number of matches between two sets of points.

    Args:
        data: data to align.
        ref: reference data.
        rotation: rotation to go from data to ref.
        translation: translation to go from data to ref.

    Returns:
        n_matches: number of correct matches.
    """
    data = data.dot(rotation.T) + translation
    return (np.linalg.norm(data - ref, axis=1) < 0.1).sum()
