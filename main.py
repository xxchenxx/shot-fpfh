import argparse
import os
import warnings
import gc

from src import (
    get_data,
    write_ply,
    checkpoint,
    best_rigid_transform,
    compute_rigid_transform_error,
    # query points sampling
    select_query_indices_randomly,
    select_query_points_iteratively,
    select_query_points_subsampling,
    # descriptors
    compute_shot_descriptor,
    compute_fpfh_descriptor,
    # matching algorithms
    basic_matching,
    double_matching_with_rejects,
    ransac_matching,
    icp_point_to_point,
    get_resulting_transform,
    read_conf_file,
    count_correct_matches,
)

warnings.filterwarnings("ignore")


def parse_args() -> argparse.Namespace:
    """
    Parses the command line arguments. Also produces the help message.
    """
    parser = argparse.ArgumentParser(
        description="SHOT descriptor performance evaluation"
    )

    parser.add_argument(
        "--file_path",
        type=str,
        default="./data/bunny_returned.ply",
        help="Path to the first point cloud to use",
    )
    parser.add_argument(
        "--ref_file_path",
        type=str,
        default="./data/bunny_original.ply",
        help="Path to the second point cloud to use (reference point cloud)",
    )
    parser.add_argument(
        "--conf_file_path",
        type=str,
        default="./data/bunny/bun.conf",
        help="Path to the .conf file used to count correct matches. Leave empty to ignore",
    )
    parser.add_argument(
        "--disable_ply_writing",
        action="store_true",
        help="Skips saving the registered point cloud as ply files.",
    )
    parser.add_argument(
        "--query_points_selection",
        choices=["random", "iterative", "subsampling"],
        type=str,
        default="random",
        help="Choice of the algorithm to select query points to compute descriptors on.",
    )
    parser.add_argument(
        "--matching_algorithm",
        choices=["simple", "double", "ransac"],
        type=str,
        default="simple",
        help="Choice of the algorithm to match descriptors.",
    )
    parser.add_argument(
        "--fpfh_radius",
        type=float,
        default=1e-2,
        help="Radius in the neighborhood search when computing SPFH.",
    )
    parser.add_argument(
        "--fpfh_n_bins", type=int, default=5, help="Number of bins in FPFH."
    )
    parser.add_argument(
        "--shot_radius",
        type=float,
        default=1e-1,
        help="Radius in the neighborhood search when computing SHOT.",
    )
    parser.add_argument(
        "--reject_threshold",
        type=float,
        default=0.8,
        help="Threshold in the double matching algorithm.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    global_timer = checkpoint()
    timer = checkpoint()
    points, normals = get_data(args.file_path)
    points_ref, normals_ref = get_data(args.ref_file_path)

    rotation, translation = None, None
    if args.conf_file_path != "":
        conf = read_conf_file(args.conf_file_path)
        rotation, translation = get_resulting_transform(
            args.file_path, args.ref_file_path, read_conf_file(args.conf_file_path)
        )

    check_transform = False  # only useful when the point cloud to align is a subset of the reference point cloud
    if check_transform:
        import matplotlib.pyplot as plt
        import numpy as np
        from sklearn.neighbors import KDTree

        aligned_points = points.dot(rotation) + translation
        plt.hist(
            np.linalg.norm(
                aligned_points
                - points_ref[
                    KDTree(points_ref)
                    .query(aligned_points, return_distance=False)
                    .squeeze()
                ],
                axis=1,
            ),
            bins=100,
        )
        plt.show()

    timer("Time spent retrieving the data")

    if args.query_points_selection == "random":
        print("\n-- Selecting query points randomly --")
        points_subset = select_query_indices_randomly(
            points.shape[0], points.shape[0] // 10
        )
        points_ref_subset = select_query_indices_randomly(
            points_ref.shape[0], points_ref.shape[0] // 10
        )
    elif args.query_points_selection == "iterative":
        print("\n-- Selecting query points iteratively --")
        points_subset = select_query_points_iteratively(
            points.shape[0], args.shot_radius / 50
        )
        points_ref_subset = select_query_points_iteratively(
            points_ref.shape[0], args.shot_radius / 50
        )
    elif args.query_points_selection == "subsampling":
        print("\n-- Selecting query points based on a subsampling on the point cloud --")
        points_subset = select_query_points_subsampling(
            points.shape[0], args.shot_radius / 50
        )
        points_ref_subset = select_query_points_subsampling(
            points_ref.shape[0], args.shot_radius / 50
        )
    else:
        raise ValueError("Incorrect query points selection algorithm.")
    timer("Time spent selecting the key points")

    print("\n-- Computing the descriptors --")
    fpfh = compute_fpfh_descriptor(
        points_subset,
        points,
        normals,
        radius=args.fpfh_radius,
        n_bins=args.fpfh_n_bins,
    )
    shot = compute_shot_descriptor(
        points[points_subset], points, normals, radius=args.shot_radius
    )
    timer(
        f"Time spent computing the descriptors on the point cloud to align ({points.shape[0]} points)"
    )

    fpfh_ref = compute_fpfh_descriptor(
        points_ref_subset,
        points_ref,
        normals_ref,
        radius=args.fpfh_radius,
        n_bins=args.fpfh_n_bins,
    )
    shot_ref = compute_shot_descriptor(
        points_ref[points_ref_subset], points_ref, normals_ref, radius=args.shot_radius
    )
    timer(
        f"Time spent computing the descriptors on the reference point cloud ({points_ref.shape[0]} points)"
    )
    gc.collect()

    # matching
    if args.matching_algorithm == "simple":
        print("\n-- Matching descriptors using simple matching to closest neighbor --")
        matches_fpfh = basic_matching(fpfh, fpfh_ref)
        timer("Time spent finding matches between the FPFH descriptors")

        # validation
        assert (
            matches_fpfh.shape[0] == fpfh.shape[0]
        ), "Not as many matches as FPFH descriptors"
        if args.conf_file_path != "":
            n_correct_matches_fpfh = count_correct_matches(
                points[points_subset],
                points_ref[points_ref_subset][matches_fpfh],
                rotation,
                translation,
            )
            print(
                f"FPFH: {n_correct_matches_fpfh} correct matches out of {fpfh.shape[0]} descriptors."
            )

        rms_fpfh, points_aligned_fpfh = compute_rigid_transform_error(
            points,
            points_ref,
            *best_rigid_transform(
                points[points_subset],
                points_ref[points_ref_subset][matches_fpfh],
            ),
        )
        timer()

        matches_shot = basic_matching(shot, shot_ref)
        timer("Time spent finding matches between the SHOT descriptors")
        assert (
            matches_shot.shape[0] == shot.shape[0]
        ), "Not as many matches as SHOT descriptors"
        if args.conf_file_path != "":
            n_correct_matches_shot = count_correct_matches(
                points[points_subset],
                points_ref[points_ref_subset][matches_shot],
                rotation,
                translation,
            )
            print(
                f"SHOT: {n_correct_matches_shot} correct matches out of {shot.shape[0]} descriptors."
            )

        rms_shot, points_aligned_shot = compute_rigid_transform_error(
            points,
            points_ref,
            *best_rigid_transform(
                points[points_subset],
                points_ref[points_ref_subset][matches_shot],
            ),
        )
        timer()
    elif args.matching_algorithm == "double":
        print("\n-- Matching descriptors using double matching with rejects --")
        matches_fpfh, matches_fpfh_ref = double_matching_with_rejects(
            fpfh, fpfh_ref, args.reject_threshold
        )
        timer("Time spent finding matches between the FPFH descriptors")

        if args.conf_file_path != "":
            n_correct_matches_fpfh = count_correct_matches(
                points[points_subset][matches_fpfh],
                points_ref[points_ref_subset][matches_fpfh_ref],
                rotation,
                translation,
            )
            print(
                f"FPFH: {n_correct_matches_fpfh} correct matches out of {fpfh.shape[0]} descriptors."
            )

        rms_fpfh, points_aligned_fpfh = compute_rigid_transform_error(
            points,
            points_ref,
            *best_rigid_transform(
                points[points_subset][matches_fpfh],
                points_ref[points_ref_subset][matches_fpfh_ref],
            ),
        )
        timer()

        matches_shot, matches_shot_ref = double_matching_with_rejects(
            shot, shot_ref, args.reject_threshold
        )
        timer("Time spent finding matches between the SHOT descriptors")

        if args.conf_file_path != "":
            n_correct_matches_shot = count_correct_matches(
                points[points_subset][matches_shot],
                points_ref[points_ref_subset][matches_shot_ref],
                rotation,
                translation,
            )
            print(
                f"SHOT: {n_correct_matches_shot} correct matches out of {shot.shape[0]} descriptors."
            )

        rms_shot, points_aligned_shot = compute_rigid_transform_error(
            points,
            points_ref,
            *best_rigid_transform(
                points[points_subset][matches_shot],
                points_ref[points_ref_subset][matches_shot_ref],
            ),
        )
        timer()
    elif args.matching_algorithm == "ransac":
        print("\n -- Matching descriptors using ransac-like matching --")
        rms_fpfh, (rotation_fpfh, translation_fpfh) = ransac_matching(
            fpfh,
            points,
            points[points_subset],
            fpfh_ref,
            points_ref,
            points_ref[points_ref_subset],
        )
        timer("Time spent finding matches between the FPFH descriptors")
        points_aligned_fpfh = points.dot(rotation_fpfh.T) + translation_fpfh
        timer()

        rms_shot, (rotation_shot, translation_shot) = ransac_matching(
            shot,
            points,
            points[points_subset],
            shot_ref,
            points_ref,
            points_ref[points_ref_subset],
        )
        timer("Time spent finding matches between the SHOT descriptors")
        points_aligned_shot = points.dot(rotation_shot.T) + translation_shot
        timer()
    else:
        raise ValueError("Incorrect matching algorithm selection.")
    gc.collect()

    print(f"\nRMS error with FPFH: {rms_fpfh:.2f}")
    print(f"RMS error with SHOT: {rms_shot:.2f}")

    # fine registration using an icp
    print("\n-- Running ICPs --")
    points_aligned_fpfh_icp, rms_fpfh_icp, has_fpfh_converged = icp_point_to_point(
        points_aligned_fpfh, points_ref
    )
    points_aligned_shot_icp, rms_shot_icp, has_shot_converged = icp_point_to_point(
        points_aligned_shot, points_ref
    )
    print(f"RMS error with FPFH + ICP: {rms_fpfh_icp:.2f}")
    print(f"RMS error with SHOT + ICP: {rms_shot_icp:.2f}")

    print(
        f"The ICP starting from the registration obtained by matching"
        f" FPFH descriptors has{'' if has_fpfh_converged else ' not'} converged."
    )
    print(
        f"The ICP starting from the registration obtained by matching"
        f" SHOT descriptors has{'' if has_shot_converged else ' not'} converged."
    )
    timer("Time spent on ICP")

    if not args.disable_ply_writing:
        print(
            "\n -- Writing the aligned points cloud in ply files under './data/results' --"
        )
        if not os.path.isdir("./data/results"):
            os.mkdir("./data/results")

        file_name = args.file_path.split("/")[-1].replace(".ply", "")
        write_ply(
            f"./data/results/{file_name}_registered_fpfh-{args.matching_algorithm}.ply",
            [points_aligned_fpfh],
            ["x", "y", "z"],
        )
        write_ply(
            f"./data/results/{file_name}_registered_shot-{args.matching_algorithm}.ply",
            [points_aligned_shot],
            ["x", "y", "z"],
        )
        write_ply(
            f"./data/results/{file_name}_registered_fpfh_icp-{args.matching_algorithm}.ply",
            [points_aligned_fpfh_icp],
            ["x", "y", "z"],
        )
        write_ply(
            f"./data/results/{file_name}_registered_shot_icp-{args.matching_algorithm}.ply",
            [points_aligned_shot_icp],
            ["x", "y", "z"],
        )

    global_timer("\nTotal time spent")
