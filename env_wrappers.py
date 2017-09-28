import cv2
import gym
import numpy as np

from collections import deque
from gym import spaces

class EpisodicLifeEnv(gym.Wrapper):
    def __init__(self, env=None):
        """
        1エピソード=1ライフにする．
        """
        super(EpisodicLifeEnv, self).__init__(env)
        self.lives = 0
        self.was_real_done = True
        self.was_real_reset = False

    def _step(self, action):
        obs, reward, done, info = self.env.step(action)
        self.was_real_done = done
        lives = self.env.unwrapped.ale.lives()
        if lives < self.lives and lives > 0:
            done = True
        self.lives = lives
        return obs, reward, done, info

    def _reset(self):
        if self.was_real_done:
            obs = self.env.reset()
            self.was_real_reset = True
        else:
            obs, _, _, _ = self.env.step(0)
            self.was_real_reset = False
        self.lives = self.env.unwrapped.ale.lives()
        return obs

class NoopResetEnv(gym.Wrapper):
    def __init__(self, env, no_op_max):
        """
        エピソードの開始時に数フレーム何もしない行動を取り，
        初期状態を決定する．
        """
        super(NoopResetEnv, self).__init__(env)
        self.no_op_max = no_op_max

    def _reset(self):
        self.env.reset()
        # ランダムなフレーム数分「何もしない」
        T = np.random.randint(1, self.no_op_max + 1)
        observation = None
        for _ in range(T):
            # 「何もしない」で，次の画面を返す
            # @todo pongの場合，0：何もしない，1：何もしない，2：上，3：下なので修正が必要と思われる
            observation, _, _, _ = self.env.step(0)
        return observation

class MaxAndSkipEnv(gym.Wrapper):
    def __init__(self, env, action_repeat):
        """
        1回行動を取ると，同じ行動を指定フレーム分続ける．
        指定数分行動を繰り返したら，直前のフレームの観測との最大値を状態として返す．
        """
        super(MaxAndSkipEnv, self).__init__(env)
        self.observation_buffer = deque(maxlen=2)
        self.action_repeat = action_repeat

    def _step(self, action):
        total_reward = 0.0
        done = None
        for _ in range(self.action_repeat):
            observation, reward, done, info = self.env.step(action)
            self.observation_buffer.append(observation)
            total_reward += reward
            if done:
                break

        # 前のフレームの観測との最大値を状態として返す
        max_frame = np.max(np.stack(self.observation_buffer), axis=0)
        return max_frame, total_reward, done, info

class FireResetEnv(gym.Wrapper):
    def __init__(self, env):
        """
        行動"Fire"を取らないと開始しないゲームの場合，
        最初に"Fire"を実行してゲームを開始させる．
        """
        super(FireResetEnv, self).__init__(env)

    def _reset(self):
        self.env.reset()
        observation, _, done, _ = self.env.step(1)
        if done:
            self.env.reset()
        observation, _, done, _ = self.env.step(2)
        if done:
            self.env.reset()
        return observation

class ProcessFrame84(gym.ObservationWrapper):
    def __init__(self, env=None):
        """
        観測した画面を(84,84)サイズのグレースケール画像に変換．
        """
        super(ProcessFrame84, self).__init__(env)
        self.observation_space = spaces.Box(low=0, high=255, shape=(84, 84, 1))

    def _observation(self, obs):
        return ProcessFrame84.process(obs)

    @staticmethod
    def process(frame):
        if frame.size == 210 * 160 * 3:
            img = np.reshape(frame, [210, 160, 3]).astype(np.float32)
        elif frame.size == 250 * 160 * 3:
            img = np.reshape(frame, [250, 160, 3]).astype(np.float32)
        else:
            assert False, "Unknown resolution."
        img = img[:, :, 0] * 0.299 + img[:, :, 1] * 0.587 + img[:, :, 2] * 0.114
        resized_screen = cv2.resize(img, (84, 110), interpolation=cv2.INTER_AREA)
        x_t = resized_screen[18:102, :]
        x_t = np.reshape(x_t, [84, 84, 1])
        return x_t.astype(np.uint8)

class FrameStack(gym.Wrapper):
    def __init__(self, env, k):
        """
        指定したフレーム数分の観測の履歴を状態とする．
        """
        gym.Wrapper.__init__(self, env)
        self.k = k
        self.frames = deque([], maxlen=k)
        shp = env.observation_space.shape
        self.observation_space = spaces.Box(low=0, high=255, shape=(k * shp[2], shp[0], shp[1]))

    def _reset(self):
        observation = self.env.reset()
        for _ in range(self.k):
            self.frames.append(observation)
        return self._get_observation()

    def _step(self, action):
        observation, reward, done, info = self.env.step(action)
        self.frames.append(observation)
        return self._get_observation(), reward, done, info

    def _get_observation(self):
        assert len(self.frames) == self.k
        return LazyFrames(list(self.frames))

class LazyFrames(object):
    def __init__(self, frames):
        self._frames = frames

    def __array__(self, dtype=None):
        out = np.concatenate(self._frames, axis=2)
        out = out.transpose(2, 0, 1)
        if dtype is not None:
            out = out.astype(dtype)
        return out

class ClippedRewardsWrapper(gym.RewardWrapper):
    def _reward(self, reward):
        """
        報酬が正なら+1に，負なら-1に，0なら0とする．
        """
        return np.sign(reward)

class ScaledFloatFrame(gym.ObservationWrapper):
    def _observation(self, observation):
        """
        状態を255で割って正規化する
        """
        return np.array(observation).astype(np.float32) / 255.0

def wrap_dqn(env):
    env = EpisodicLifeEnv(env)
    env = NoopResetEnv(env, no_op_max=30)
    env = MaxAndSkipEnv(env, action_repeat=4)
    if 'FIRE' in env.unwrapped.get_action_meanings():
        env = FireResetEnv(env)
    env = ProcessFrame84(env)
    env = FrameStack(env, 4)
    env = ClippedRewardsWrapper(env)
    env = ScaledFloatFrame(env)
    return env
