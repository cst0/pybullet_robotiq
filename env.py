import numpy as np
import pybullet as p
import pybullet_data
import gym

from robot import KinovaRobotiq85
from robot import MOVE_CHUNK_COUNT as ROBOT_MOVE_CHUNKS
from violations import CollisionViolation

from utilities import Models
from task import Task


class FailToReachTargetError(RuntimeError):
    pass


class EmptyScene(gym.Env):

    SIMULATION_STEP_DELAY = 1 / 240.0

    def __init__(
        self, robot: KinovaRobotiq85, models: Models, camera=None, vis=False
    ) -> None:
        super().__init__()
        self.robot = robot
        self.models = models
        self.vis = vis
        self.camera = camera
        self.steps = 0
        self.violates_limits = False  # assume that we start in a non-violating state

        # define environment
        self.physicsClient = p.connect(p.GUI if self.vis else p.DIRECT)
        p.setTimeStep(0.01)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -10)
        self.planeID = p.loadURDF("plane.urdf")

        self.robot.load()
        self.robot.step_simulation = self.step_simulation

        self.joint_debug_params = []
        self.gripper_opening_length_control = None
        if self.vis:
            self.joint_debug_params = [
                p.addUserDebugParameter(
                    "joint_{}".format(i),
                    -p.getJointInfo(self.robot.id, i)[11],
                    p.getJointInfo(self.robot.id, i)[11],
                    0,
                )
                for i in self.robot.arm_dof_ids
            ]

            self.gripper_opening_length_control = p.addUserDebugParameter(
                "gripper_opening_length", 0, 0.085, 0.04
            )

        self.reward = 0
        self.task = Task()

        # our action space is to select a specific joint and move that joint to the next point.
        # we can move a joint in either direction, and there are 8 joints, so we have 16 possible actions.
        self.observation_space = gym.spaces.MultiDiscrete(
            np.ones(7) * ROBOT_MOVE_CHUNKS
        )
        self.action_space = gym.spaces.Discrete(
            self.robot.arm_num_dofs * 2
        )  # arm dof's left and right

        self.collision_violation = CollisionViolation(
            {
                "joint_ids": [0, 1, 2, 3, 4, 5, 6],
                "object_id_self": self.robot.id,
                "object_ids_env": [self.planeID],
            }
        )

    def get_joint_limits(self):
        limits = []
        for i in range(self.robot.arm_num_dofs):
            limits.append(
                p.getJointInfo(self.robot.id, self.robot.arm_dof_ids[i])[8:10]
            )
        return limits

    def create_object(self, urdf_path, position, orientation):
        return p.loadURDF(urdf_path, position, orientation)

    def set_task(self, task: Task):
        self.task = task

    def step_simulation(self):
        self.steps += 1
        p.stepSimulation()

    def read_debug_parameter(self):
        # read the value of task parameter
        read_vals = [
            p.readUserDebugParameter(param)
            for param in self.joint_debug_params + [self.gripper_opening_length_control]
        ]

        return read_vals

    def step(self, action):
        if action < self.robot.arm_num_dofs * 2:
            return_action = [0] * self.robot.arm_num_dofs
            joint_index = action // 2
            direction = action % 2
            return_action[joint_index] = -1 if direction == 0 else 1

            success = self.robot.move_arm_step(return_action)
            if not success:
                self.violates_limits = True

        # elif action == self.robot.arm_num_dofs * 2:
        #     self.robot.open_gripper()
        # elif action == self.robot.arm_num_dofs * 2 + 1:
        #     self.robot.close_gripper()
        #
        # else:
        #    self.robot.move_arm_bonus(action)

        for _ in range(10):  # Wait for a few steps
            self.step_simulation()
        done = True if self.task.is_done() else False
        reward = self.update_reward(done)
        return self.get_observation(), reward, done, {}

    def update_reward(self, is_done):
        last_reward = self.reward
        self.reward = self.task.reward()
        extra_punish = 0
        if last_reward > self.reward:
            extra_punish -= 1  # punish stepping away from the goal
        # current_collisions = self.collision_violation.find_active_collision()
        # if len(current_collisions) > 0:
        #    extra_punish -= 1  # punish collision
        if self.violates_limits:
            extra_punish -= 1
            self.violates_limits = False
        if is_done:
            extra_punish += 10  # reward reaching the goal
        return self.reward + extra_punish

    def map_observation(self, obs):
        for i in range(len(obs)):
            # map to [0, 2*pi]
            obs[i] = (obs[i] + np.pi) % (2 * np.pi)
            # now map to [0, ROBOT_MOVE_CHUNKS)
            obs[i] = int(obs[i] / (2 * np.pi) * ROBOT_MOVE_CHUNKS)
        return obs

    def get_observation(self):
        # construct a unique mapping from joint position to observation
        obs = np.zeros(self.robot.arm_num_dofs)
        for i, _id in enumerate(self.robot.arm_dof_ids):
            raw_value = p.getJointState(self.robot.id, _id)[0]
            obs[i] = raw_value
        return self.map_observation(obs)

    def reset(self):
        self.steps = 0
        self.reward = 0
        self.robot.reset()
        return self.get_observation()

    def close(self):
        p.disconnect(self.physicsClient)

    def render(self, mode="human"):
        pass
