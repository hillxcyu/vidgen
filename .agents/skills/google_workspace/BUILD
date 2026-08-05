load("//learning/gemini/agents/skill_rules:skills.bzl", "agent_skill")
load("//learning/gemini/agents/skills/skill_creator/scripts:skill_defs.bzl", "validate_skill_test")

package(default_visibility = [
    "//geo/automotive:__subpackages__",
    "//learning/gemini/agents/skills:__subpackages__",
    "//retail/analytics/data_detective:__subpackages__",
])

agent_skill(
    name = "google_workspace",
    srcs = ["SKILL.md"],
)

validate_skill_test(
    name = "validate_google_workspace_skill_test",
)
