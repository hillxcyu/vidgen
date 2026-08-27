import os


def test_prompts_exist():
    assert os.path.exists("app/prompts/pre_prod_system.txt")
    assert os.path.exists("app/prompts/prod_loop_system.txt")

    with open("app/prompts/pre_prod_system.txt", "r", encoding="utf-8") as f:
        pre_prod = f.read()
        assert "SCREENWRITER" in pre_prod
        assert "STORYBOARDER" in pre_prod

    with open("app/prompts/prod_loop_system.txt", "r", encoding="utf-8") as f:
        prod_loop = f.read()
        assert "PROMPT OPTIMIZER" in prod_loop
        assert "HEALTH CHECKER" in prod_loop
        assert "QUALITY RATER" in prod_loop
        assert "SINGLE-SHOT RULE" in prod_loop
        assert "DIALOGUE RULE" in prod_loop
        assert "diffusion identity drift" in prod_loop
