#! /usr/bin/env python
from __future__ import print_function

import sys
import copy
import time
import rospy
import math
import tf

import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.image as mpimg

from std_msgs.msg import String, Float64
from geometry_msgs.msg import Point
from sensor_msgs.msg import Image, CameraInfo, CompressedImage
from cv_bridge import CvBridge, CvBridgeError
import message_filters
sys.path.append("./src/gem_vision/camera_vision/scripts/Detector/")
from yolo_detect_image import yolo_detect_image
sys.path.append("./src/gem_vision/camera_vision/scripts/lane_detect/")
from lane_detector import lane_detector
from camera_vision.msg import Detected_info

class ImageConverter:
    def __init__(self):
        self.node_name = "gem_vision"
        rospy.init_node(self.node_name)
        rospy.on_shutdown(self.cleanup)
        self.bridge = CvBridge()
        # Subscribe camera rgb and depth information
        depth_img_topic = rospy.get_param('depth_info_topic','/zed2/zed_node/depth/depth_registered')
        self.depth_img_sub = message_filters.Subscriber(depth_img_topic,Image)
        self.subcriber_rgb = message_filters.Subscriber('/zed2/zed_node/rgb/image_rect_color', Image)
        # subcriber_depth = message_filters.Subscriber('/zed2/zed_node/depth/depth_registered', Image)
        self.subcriber_rgb_camera = message_filters.Subscriber('/zed2/zed_node/rgb_raw/camera_info', CameraInfo)
        sync = message_filters.ApproximateTimeSynchronizer([self.subcriber_rgb, self.depth_img_sub, self.subcriber_rgb_camera], 10, 1)
        sync.registerCallback(self.multi_callback)
        # Publish Boudingbox information of objects
        self.image_pub = rospy.Publisher("/object_detection", Detected_info, queue_size=1)
        self.last_state_info = [[], []]

    def cv2imshow(self, frame, frame_name, mode):
        cv2.imshow(frame_name, frame)
        if mode == 0:
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        elif mode == 1:
            cv2.waitKey(1)

    def calculate_object_distance(self, detected_list, depth_frame, camera_info, bbx_frame):
        camera_coordinate_list = []
        # Camera Intrinsic Information
        fx = camera_info.K[0]
        fy = camera_info.K[4]
        cx = camera_info.K[2]
        cy = camera_info.K[5]
        inv_fx = 1. / fx
        inv_fy = 1. / fy
        for i in range(len(detected_list)):
            left_top_x = detected_list[i][0]
            left_top_y = detected_list[i][1]
            right_down_x = detected_list[i][2]
            right_down_y = detected_list[i][3]
            classId = detected_list[i][4]
            confidence = detected_list[i][5]
            center_y = (left_top_y + right_down_y) / 2
            center_x = (left_top_x + right_down_x) / 2
            width = right_down_x - left_top_x
            height = right_down_y - left_top_y
            # Crop detected objects in depth img
            detected_depth = np.array(depth_frame[left_top_y : right_down_y, left_top_x : right_down_x])
            detected_depth = detected_depth[np.where(detected_depth > 0)]
            detected_depth = detected_depth[np.where(detected_depth < 100)]
            # print("detected_depth", detected_depth)
            # print("detected_depth.shape", detected_depth.shape)
            # print(detected_list[i][0], detected_list[i][2], detected_list[i][1], detected_list[i][3])
            # Transform from pixel coordinate to camera coordinate
            if detected_depth.shape[0] == 0:
                camera_x = -1
                camera_y = -1
                camera_z = -1
                distance = -1
                camera_coordinate = [distance, camera_x, camera_y, classId, confidence, camera_z]
            else:
                camera_z = int(np.mean(detected_depth))
                camera_x = ((center_x + width / 2) - cx) * camera_z * inv_fx
                camera_y = ((center_y + height / 2) - cy) * camera_z * inv_fy
                distance = math.sqrt(camera_x ** 2 + camera_y ** 2 + camera_z ** 2)
                camera_coordinate = [distance, camera_x, camera_y, classId, confidence, camera_z]
            camera_coordinate_list.append(camera_coordinate)
            # Draw distances 
            x_str = "X: " + str(format(camera_x, '.3f'))
            y_str = "Y: " + str(format(camera_y, '.3f'))
            z_str = "Z: " + str(format(camera_z, '.3f'))
            cv2.putText(bbx_frame, x_str, (int(center_x+width), int(center_y)+20), cv2.FONT_HERSHEY_SIMPLEX,  
                    0.7, (0,0,255), 1, cv2.LINE_AA) 
            cv2.putText(bbx_frame, y_str, (int(center_x+width), int(center_y)+40), cv2.FONT_HERSHEY_SIMPLEX,  
                    0.7, (0,0,255), 1, cv2.LINE_AA)
            cv2.putText(bbx_frame, z_str, (int(center_x+width), int(center_y)+60), cv2.FONT_HERSHEY_SIMPLEX,  
                    0.7, (0,0,255), 1, cv2.LINE_AA)
            dist_str = "dist:" + str(format(distance, '.2f')) + "m"
            cv2.putText(bbx_frame, dist_str, (int(center_x+width), int(center_y)+80), cv2.FONT_HERSHEY_SIMPLEX,  
                0.7, (0,255,0), 1, cv2.LINE_AA)

        # rgb_height, rgb_width, rgb_channels = bbx_frame.shape

        # # 在图像中心画轴
        # cv2.line(bbx_frame,(int(rgb_width/2),int(rgb_height/2)),(int(rgb_width/2)+150,int(rgb_height/2)),(0,255,0),2)
        # cv2.line(bbx_frame,(int(rgb_width/2),int(rgb_height/2)),(int(rgb_width/2),int(rgb_height/2)+150),(0,255,0),2)
        # cv2.putText(bbx_frame, "x axis", (int(rgb_width/2)+180,int(rgb_height/2)), cv2.FONT_HERSHEY_SIMPLEX,  
        #         0.7, (200,255,0), 1, cv2.LINE_AA)
        # cv2.putText(bbx_frame, "y axis", (int(rgb_width/2),int(rgb_height/2)+180), cv2.FONT_HERSHEY_SIMPLEX,  
        #         0.7, (125,255,0), 1, cv2.LINE_AA)

        # print("distance_list,", distance_list)
        return camera_coordinate_list, bbx_frame

    def calculate_lane_distance(self, middle_lane, depth_frame, camera_info, bbx_frame):
        camera_coordinate_list = []
        # Camera Intrinsic Information
        fx = camera_info.K[0]
        fy = camera_info.K[4]
        cx = camera_info.K[2]
        cy = camera_info.K[5]
        inv_fx = 1. / fx
        inv_fy = 1. / fy
        for i in range(len(middle_lane)):
            center_y = middle_lane[i][0]
            center_x = middle_lane[i][1]
            width = 30
            height = 30
            # Crop detected objects in depth img
            detected_depth = np.array(depth_frame[int(center_y - height / 2) : int(center_y + height / 2), int(center_x - width / 2): int(center_x + width / 2)])
            detected_depth = detected_depth[np.where(detected_depth > 0)]
            detected_depth = detected_depth[np.where(detected_depth < 100)]
            # print("detected_depth", detected_depth)
            # print("detected_depth.shape", detected_depth.shape)
            # print(detected_list[i][0], detected_list[i][2], detected_list[i][1], detected_list[i][3])
            # Transform from pixel coordinate to camera coordinate
            if detected_depth.shape[0] == 0:
                camera_x = -1
                camera_y = -1
                camera_z = -1
                distance = -1
                camera_coordinate = [distance, camera_x, camera_y, camera_z]
            else:
                camera_z = int(np.mean(detected_depth))
                camera_x = ((center_x + width / 2) - cx) * camera_z * inv_fx
                camera_y = ((center_y + height / 2) - cy) * camera_z * inv_fy
                distance = math.sqrt(camera_x ** 2 + camera_y ** 2 + camera_z ** 2)
                camera_coordinate = [distance, camera_x, camera_y, camera_z]
            camera_coordinate_list.append(camera_coordinate)
            # print("distance,", distance)
        return camera_coordinate_list, bbx_frame
        

    def multi_callback(self, rgb, depth, camera_info):
        # Get rgb and depth image in cv2 format respectively
        try:
            rgb_frame = self.bridge.imgmsg_to_cv2(rgb, "bgr8")
            depth_frame = self.bridge.imgmsg_to_cv2(depth, "32FC1")
            # print("rgb_frame", rgb_frame.shape)
            # print("depth_frame", depth_frame.shape)
        except CvBridgeError as e:
            rospy.logerr("CvBridge Error: {0}".format(e))
        # ----------------- Imaging processing code starts here ----------------\
        # Object Detection with Yolov3 through OpenCV
        detected_list, bbx_frame = yolo_detect_image(rgb_frame)
        # print("Detected Objects", detected_list)
        # self.cv2imshow(bbx_frame, "bbx_frame", 1)
        
        object_camera_coordinate_list, bbx_frame = self.calculate_object_distance(detected_list, depth_frame, camera_info, bbx_frame)
        # print("distance_list", distance_list)
        # self.cv2imshow(bbx_frame, "bbx_frame", 1)

        middle_lane, bbx_frame, curren_state_info = lane_detector(rgb_frame, bbx_frame, self.last_state_info)
        self.last_state_info = curren_state_info
        # self.cv2imshow(img_with_lane_bbxs, "img_with_lane_bbxs", 1)

        lane_camera_coordinate_list, bbx_frame  = self.calculate_lane_distance(middle_lane, depth_frame, camera_info, bbx_frame)
        self.cv2imshow(bbx_frame, "bbx_frame", 1)

        detectBox = Detected_info()
        for i in range(len(middle_lane)):
            detectBox.middle_lane.append(lane_camera_coordinate_list[i][0])
            detectBox.middle_lane.append(lane_camera_coordinate_list[i][1])
            detectBox.middle_lane.append(lane_camera_coordinate_list[i][2])
        for i in  range(len(detected_list)):
            detectBox.object_distance.append(object_camera_coordinate_list[i][0])
            detectBox.object_x.append(object_camera_coordinate_list[i][1])
            detectBox.object_y.append(object_camera_coordinate_list[i][2])
            detectBox.classId.append(object_camera_coordinate_list[i][3])
            detectBox.confidence.append(object_camera_coordinate_list[i][4])
        # ----------------------------------------------------------------------
        self.image_pub.publish(detectBox)

    def cleanup(self):
        print ("Shutting down vision node.")
        cv2.destroyAllWindows()

def main(args):
    try:
        ImageConverter()
        rospy.spin()
    except KeyboardInterrupt:
        print("Shutting down vision node.")
        cv2.destryAllWindows()

if __name__ == '__main__':
    main(sys.argv)

    