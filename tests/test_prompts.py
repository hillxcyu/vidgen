import os

def test_prompts_exist_and_nonempty():
    pre_prod_path = "src/prompts/pre_prod_system.txt"
    prod_loop_path = "src/prompts/prod_loop_system.txt"

    assert os.path.exists(pre_prod_path)
    assert os.path.exists(prod_loop_path)

    with open(pre_prod_path, "r", encoding="utf-8") as f:
        pre_prod_content = f.read()
    assert "SCREENWRITER" in pre_prod_content
    assert "STORYBOARDER" in pre_prod_content

    with open(prod_loop_path, "r", encoding="utf-8") as f:
        prod_loop_content = f.read()
    assert "PROMPT OPTIMIZER" in prod_loop_content
    assert "QUALITY RATER" in prod_loop_content
