Upper body skeleton estimator
=============================

This package estimates the 3d positions of the 9 upper body skeleton
joints.

Launching
---------

Use the following launchfile for launching:

::

    roslaunch rwth_upper_body_skeleton_random_walk fixed.launch 

The skeleton detector requires the output of the upper body detector as
a starting point for rough person segmentation from background and will
not work if upper bodies are not detected.

Run
===

Dependencies
------------

This node needs ``upper_body_detector/upper_body_detector.launch`` to
run, which in turn needs
``ground_plane_estimation/ground_plane_fixed.launch``.

Parameters
----------

-  ``depth_image_msg`` \*default =
   /head\_xtion/depth/image\_rect\_meters: Depth Image Frame.
-  ``upper_body_msg`` \*default = /upper\_body\_detector/detections: The
   deteced upper bodies
-  ``rgb_image_msg`` \*default = /head\_xtion/rgb/image\_rect\_color:
   RGB Image Frame.

roslaunch
---------

::

    roslaunch rwth_upper_body_skeleton_random_walk fixed.launch  [parameter_name:=value]



Original page: https://github.com/strands-project/strands_perception_people/blob/indigo-devel/rwth_upper_body_skeleton_random_walk/README.md