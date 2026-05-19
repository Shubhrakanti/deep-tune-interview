# RL Environment Hackathon

Today, you will be building a MVP for a computer use RL environment. There are three main parts to building an environment:

1. **The gym:** The software environment with realistic world data. You will be building an environment for Metabase using their public sample data.
2. **The agent:** the agent with the tools it needs to navigate its environment and solve the task
3. **The infra:** infrastructure to orchestrate running the agent inside of the environment to get reward

Materials you will need:

- https://github.com/metabase/metabase (run this with Docker and sample data)
- https://github.com/google-gemini/computer-use-preview (for the agent)
- And:
    
    [tasks.json](attachment:7aed0b64-b8f4-40fa-8e97-e689febc9550:tasks.json)
    
    [metabase_envdata.sql](attachment:a759e60b-d04a-4817-9692-bcda8d8c5236:metabase_envdata.sql)
    
    - Note: this is not data for a Metabase “database connection”. It is environment data for the Metabase app itself.
- Login info: `daksh@deeptune.com`, `Daksh@123`


<aside>
🔑

If you get stuck or have any questions, please ask! How you think about the problem is just as important as total progress.

</aside>

# Deliverables

- [ ]  **Milestone 1:** Build the environment. This includes:
    - Getting the computer use agent running with Metabase locally.
    - Metabase should initialize with the provided realistic environment data at runtime.
    - The agent should be given a prompt and graded on whether or not it can successfully complete the prompt.
- [ ]  **Milestone 2:** Build the infrastructure to create rollouts. This includes:
    - A basic platform that can ingest the `tasks.json` file and run rollouts on your environment locally.
    - The frontend for the platform should allow you to:
        - Submit jobs using a problem file like above.
        - Specify the number of attempts per problem in your job.
        - Visually view the transcripts and grade for each problem run in a job.
- [ ]  **Milestone 3:** Design a productionized version.
    - Come up with a plan to productionize the platform:
        - What if the agent writes in addition to reads?
        - What if we want to scale this to 1000s of rollouts?