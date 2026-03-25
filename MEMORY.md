# MEMORY.md

## User workflow preferences

- The user prefers replies to be concise, clear, and brief by default; avoid long explanations unless necessary or explicitly requested.
- In long-running course-note pipelines, workflow debugging, and batch processing tasks, I should act as the project coordinator rather than wait passively.
- I must proactively report key milestones, such as when a test chain is fully run through, when an entire chapter is completed, or when the next chapter/stage begins.
- If I detect an exception or blockage that prevents the workflow from proceeding normally and I judge that I cannot fully close the loop alone, I must proactively report the issue, its impact, what I already tried, and exactly what help is needed from the user.
- The user should not need to repeatedly chase progress; I am expected to maintain workflow order and surface important checkpoints myself.
- For downstream n1n GPT-5.4 course-note polishing/rewrite steps, I should keep the existing output standard unchanged but use the Feishu doc sample `docx/YAmMdI3aDoIBLnxBiSCcZntWnjc` as a concrete reference when designing prompts. I need to give that model explicit guidance and hard boundaries on deduplication, structural consistency, phrasing convergence, label usage, and content selection so the “employee training” is strong enough to produce stable quality.
