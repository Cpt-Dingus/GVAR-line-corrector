# GVAR line corrector
This python script attempts to correct misplaced lines from within a .gvar file

## Usage
To use, run it from your command prompt as such: `python main.py -i <input_file_name> -o <output_file_name>`

## How it does this
GVAR is an incredibly inconsistent format owing to its name - **Variable**. Thankfully, it transmits blocks in a consecutive order with 1-10 all containing a line header! After applying majority law correction to the header and this counter, a lot of misplaced lines should be fine now.

Before:
![Full disc GVAR crop with several missing lines](https://github.com/Cpt-Dingus/GVAR-line-corrector/assets/100243410/af217faa-6dca-42e2-9c8f-ed22e4391065)

After:
![Full disc GVAR crop with much fewer missing lines](https://github.com/Cpt-Dingus/GVAR-line-corrector/assets/100243410/48c5a50d-f92f-40b3-a32f-55af66136167)


A huge thanks to @sealsrock and @that_zbychu on Discord for helping with developing the correction process!
