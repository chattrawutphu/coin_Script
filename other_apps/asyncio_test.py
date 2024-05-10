import asyncio
import random
import time
import aiofiles
import os

async def my_function(param, fixed_time, file):
    count = 0
    while True:
        start_time = time.time()
        await asyncio.sleep(fixed_time)
        result = f"Processed {param}, Round: {count}, Time: {time.time() - start_time:.2f}s"
        print(result)

        if not os.path.isfile(file):
            open(file, 'w').close()

        async with aiofiles.open(file, 'a') as f:
            await f.write(result + '\n')

        count += 1

async def main():
    params = range(1000)
    file_path = "data.txt"

    fixed_times = [random.uniform(1, 10000) for _ in params]

    coroutines = [my_function(param, fixed_time, file_path) for param, fixed_time in zip(params, fixed_times)]

    await asyncio.gather(*coroutines)

if __name__ == "__main__":
    asyncio.run(main())
