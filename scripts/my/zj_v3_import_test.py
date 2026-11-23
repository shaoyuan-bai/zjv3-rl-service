import gymnasium
import isaaclab_tasks

print("ZJV3_REGISTERED", "Isaac-ZJV3-Velocity-v0" in gymnasium.registry)
spec = gymnasium.spec("Isaac-ZJV3-Velocity-v0")
print(spec.kwargs)
