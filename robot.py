import pybullet as p
import numpy as np
import math
from collections import namedtuple

# MOVE_CHUNK = (np.pi / 10)
MOVE_CHUNK_COUNT = 60


class KinovaRobotiq85(object):
    def __init__(self, pos, ori, extra_action_count=0):
        self.base_pos = pos
        self.base_ori_rpy = ori
        self.base_ori = p.getQuaternionFromEuler(ori)
        self.id = None
        self.extra_action_count = extra_action_count
        self.bonus_actions = []
        self.is_gripper_closed = False

    def joint_position_to_observation(self, joint_position):
        positions = []
        for jp in joint_position:
            jp = jp % (np.pi * 2)
            # now the joint position is in the range of [0, 2pi],
            # place it in one of the MOVE_CHUNK_COUNT bins
            jp = int(jp / (np.pi * 2) * MOVE_CHUNK_COUNT)
            positions.append(jp)
        if tuple(positions) in self.joint_positions:
            return self.joint_positions[tuple(positions)]
        else:
            raise RuntimeError("Joint position not found in joint_positions")

    def load(self):
        self.__init_robot__()
        self.__parse_joint_info__()
        self.__post_load__()

    def step_simulation(self):
        raise RuntimeError(
            "`step_simulation` method of RobotBase Class should be hooked by the environment."
        )

    def __parse_joint_info__(self):
        assert self.id is not None
        numJoints = p.getNumJoints(self.id)
        jointInfo = namedtuple(
            "jointInfo",
            [
                "id",
                "name",
                "type",
                "damping",
                "friction",
                "lowerLimit",
                "upperLimit",
                "maxForce",
                "maxVelocity",
                "controllable",
            ],
        )
        self.joints = []
        self.controllable_joints = []
        for i in range(numJoints):
            info = p.getJointInfo(self.id, i)
            jointID = info[0]
            jointName = info[1].decode("utf-8")
            jointType = info[
                2
            ]  # JOINT_REVOLUTE, JOINT_PRISMATIC, JOINT_SPHERICAL, JOINT_PLANAR, JOINT_FIXED
            jointDamping = info[6]
            jointFriction = info[7]
            jointLowerLimit = info[8]
            jointUpperLimit = info[9]
            jointMaxForce = info[10]
            jointMaxVelocity = info[11]
            controllable = jointType != p.JOINT_FIXED
            if controllable:
                self.controllable_joints.append(jointID)
                p.setJointMotorControl2(
                    self.id, jointID, p.VELOCITY_CONTROL, targetVelocity=0, force=0
                )
            info = jointInfo(
                jointID,
                jointName,
                jointType,
                jointDamping,
                jointFriction,
                jointLowerLimit,
                jointUpperLimit,
                jointMaxForce,
                jointMaxVelocity,
                controllable,
            )
            self.joints.append(info)

        assert len(self.controllable_joints) >= self.arm_num_dofs
        self.arm_controllable_joints = self.controllable_joints[: self.arm_num_dofs]

        self.arm_lower_limits = [
            info.lowerLimit for info in self.joints if info.controllable
        ][: self.arm_num_dofs]
        self.arm_upper_limits = [
            info.upperLimit for info in self.joints if info.controllable
        ][: self.arm_num_dofs]
        self.arm_joint_ranges = [
            info.upperLimit - info.lowerLimit
            for info in self.joints
            if info.controllable
        ][: self.arm_num_dofs]

    def reset(self):
        self.reset_arm()
        self.reset_gripper()

    def reset_arm(self):
        """
        reset to rest poses
        """
        for rest_pose, joint_id in zip(
            self.arm_rest_poses, self.arm_controllable_joints
        ):
            p.resetJointState(self.id, joint_id, rest_pose)

        # Wait for a few steps
        for _ in range(10):
            self.step_simulation()

    def reset_gripper(self):
        self.open_gripper()

    def open_gripper(self):
        self.move_gripper(self.gripper_range[1])
        self.is_gripper_closed = False

    def close_gripper(self):
        self.move_gripper(self.gripper_range[0])
        self.is_gripper_closed = True

    def get_joint_obs(self):
        positions = []
        # velocities = []
        for joint_id in self.controllable_joints:
            pos, vel, _, _ = p.getJointState(self.id, joint_id)
            positions.append(pos)
            # velocities.append(vel)
        # ee_pos = p.getLinkState(self.id, self.eef_id)[0]
        return dict(
            positions=positions,
            # velocities=velocities,
            # ee_pos=ee_pos
        )

    def go_to_action_index(self, action_index):
        """
        Go to a specific action index
        """
        try:
            joint_position = list(self.joint_positions.keys())[action_index]
            self.move_arm_pos(joint_position)
        except IndexError:
            print(
                "Invalid action index: {} of {}".format(
                    action_index, len(self.joint_positions)
                )
            )

    def __init_robot__(self):
        self.arm_num_dofs = 7
        self.eef_id = 8
        self.arm_rest_poses = [
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ]

        self.arm_dof_ids = [1, 2, 3, 4, 5, 6, 7]

        self.id = p.loadURDF(
            "./urdf/kinova_robotiq_85.urdf",
            self.base_pos,
            self.base_ori,
            useFixedBase=True,
            flags=p.URDF_ENABLE_CACHED_GRAPHICS_SHAPES,
        )
        self.gripper_range = [0, 0.085]

    def move_arm(self, action):
        self.move_arm_pos(action)

    def move_arm_step(self, action):
        self.move_arm_step_pos(action)

    def move_arm_bonus(self, action):
        self.move_arm_bonus_pos(action)

    def move_arm_step_vel(self, action):
        current_joint_velocities = [
            p.getJointState(self.id, joint_id)[1]
            for joint_id in self.arm_controllable_joints
        ]
        target_joint_velocities = [
            action[i] * 0.5 if action[i] != 0 else current_joint_velocities[i]
            for i in range(self.arm_num_dofs)
        ]
        self.move_arm_vel(target_joint_velocities)

    def move_arm_step_pos(self, action):
        self.last_action = action
        current_joint_positions = [
            p.getJointState(self.id, joint_id)[0]
            for joint_id in self.arm_controllable_joints
        ]
        target_joint_positions = [
            current_joint_positions[i] + (action[i] * 1 / MOVE_CHUNK_COUNT)
            for i in range(self.arm_num_dofs)
        ]
        #if self.violates_limits(target_joint_positions):
        #    return False
        return self.move_arm_pos(target_joint_positions)

    def move_arm_pos(self, action):
        for i, j in enumerate(self.arm_dof_ids):
            p.setJointMotorControl2(
                self.id,
                j,
                p.POSITION_CONTROL,
                targetPosition=action[i],
                force=self.joints[j].maxForce * 100,
                maxVelocity=self.joints[j].maxVelocity,
            )
        return not self.in_collision()

    def in_collision(self):
        return p.getContactPoints(self.id) != []

    def violates_limits(self, target_joint_positions):
        return any(
            [
                target_joint_positions[i] < self.arm_lower_limits[i]
                or target_joint_positions[i] > self.arm_upper_limits[i]
                for i in range(self.arm_num_dofs)
            ]
        )

    def move_arm_vel(self, action):
        for i, j in enumerate(self.arm_dof_ids):
            p.setJointMotorControl2(
                self.id,
                j,
                p.VELOCITY_CONTROL,
                targetVelocity=action[i],
                force=self.joints[j].maxForce * 100,
                maxVelocity=self.joints[j].maxVelocity,
            )

    def move_arm_bonus_pos(self, action):
        action_id = abs(self.extra_action_count - action)
        action = self.bonus_actions[action_id]
        for i, j in enumerate(self.arm_dof_ids):
            p.setJointMotorControl2(
                self.id,
                j,
                p.POSITION_CONTROL,
                targetPosition=action[i],
                force=self.joints[j].maxForce * 100,
                maxVelocity=self.joints[j].maxVelocity,
            )

    def construct_new_position_actions(self):
        self.bonus_actions = []
        for i in range(self.extra_action_count):
            action = np.zeros(self.arm_num_dofs)
            for n in range(self.arm_num_dofs):
                joint_pos = np.random.uniform(
                    self.arm_lower_limits[n], self.arm_upper_limits[n]
                )
                action[n] = joint_pos
            self.bonus_actions.append(action)

    def __post_load__(self):
        # To control the gripper
        mimic_parent_name = "finger_joint"
        mimic_children_names = {
            "right_outer_knuckle_joint": 1,
            "left_inner_knuckle_joint": 1,
            "right_inner_knuckle_joint": 1,
            "left_inner_finger_joint": -1,
            "right_inner_finger_joint": -1,
        }
        self.__setup_mimic_joints__(mimic_parent_name, mimic_children_names)

    def __setup_mimic_joints__(self, mimic_parent_name, mimic_children_names):
        self.mimic_parent_id = [
            joint.id for joint in self.joints if joint.name == mimic_parent_name
        ][0]
        self.mimic_child_multiplier = {
            joint.id: mimic_children_names[joint.name]
            for joint in self.joints
            if joint.name in mimic_children_names
        }

        for joint_id, multiplier in self.mimic_child_multiplier.items():
            c = p.createConstraint(
                self.id,
                self.mimic_parent_id,
                self.id,
                joint_id,
                jointType=p.JOINT_GEAR,
                jointAxis=[0, 1, 0],
                parentFramePosition=[0, 0, 0],
                childFramePosition=[0, 0, 0],
            )
            p.changeConstraint(
                c, gearRatio=-multiplier, maxForce=100, erp=1
            )  # Note: the mysterious `erp` is of EXTREME importance

    def move_gripper(self, open_length):
        # open_length = np.clip(open_length, *self.gripper_range)
        open_angle = 0.715 - math.asin(
            (open_length - 0.010) / 0.1143
        )  # angle calculation
        # Control the mimic gripper joint(s)
        p.setJointMotorControl2(
            self.id,
            self.mimic_parent_id,
            p.POSITION_CONTROL,
            targetPosition=open_angle,
            force=self.joints[self.mimic_parent_id].maxForce,
            maxVelocity=self.joints[self.mimic_parent_id].maxVelocity,
        )
