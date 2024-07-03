import argparse
import sys


# - CONFIG -

CONSISTENCY_CHECK = 5
CURRENT_FRAME = 0
FRAME_LIMIT = 10e7


# - VARS -

TOTAL_FRAME_COUNT = 0
LAST_BLOCK_ID = 0


# - TODOS -

# TODO: Check delta between last frames, abort if it's larger than N
# i.e. if the last series was 1300 and this one is 1, don't correct it - something's wrong

# TODO: What if a block is missing? It could lead to a perpetual mismatch
# 1560 - 1561 is skipped - 1560 is still sureshot so 1562 is replaced with 1561, 1561 is set to be sureshot?

# TODO: Use the logging module.


# - ARG PARSING -

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--input", required=True, help="Input file name")
parser.add_argument("-o", "--output", required=False, help="Output file name")
input_file = parser.parse_args().input
output_file = parser.parse_args().output

if not output_file:
    output_file = "goes_gvar_corrected.gvar"

print(
    """ 
-> Made by Cpt-Dingus <-
-> v1.0.1 - 03/07/2024 <-
    """
)


# - FUNCTIONS -


def exit_gracefully() -> None:
    """Exists the program gracefully"""
    print("Total frames checked: ", TOTAL_FRAME_COUNT)
    sys.exit()


def get_header(frame: bytes) -> bytes:
    """Applies majority law error correction to the triple redundant header in the FRAM
    This if performed to ensure the block ID is correct as often as possible

    Args:
        frame (bytes): The frame to get the headers from

    Returns:
        bytes: The final header calculated using majority law EC
    """

    headers = []
    for i in range(3):
        headers.append(
            #    SYNC|HEADER START|SYNC|H.START|H.END
            frame[(8 + (i * 30)) : 8 + (i * 30) + 30]
        )

    # No headers were decoded (EOF)
    if not headers[0]:
        exit_gracefully()

    # Majority law EC between 3 headers is applied:

    # Load each header
    a = headers[0]
    b = headers[1]
    c = headers[2]

    result = bytearray(len(a))

    for i in range(len(a)):
        # Count the occurrence of each byte value at position i
        votes = {a[i]: 0, b[i]: 0, c[i]: 0}
        votes[a[i]] += 1
        votes[b[i]] += 1
        votes[c[i]] += 1

        # Determine the majority byte
        majority_byte = max(votes, key=votes.get)

        # Set the majority byte in the result array
        result[i] = majority_byte

    return bytes(result)


def get_line_counter_from_frame(frame: bytes) -> int:
    """Gets data from the line header from within a frame

    Args:
        frame (bytes): The frame to grab the header from

    Raises:
        ValueError: If the header isn't 28 bytes long (This shouldn't be possible)

    Returns:
        int: The relative scan count
    """

    # Check if input data is correct length (28 bytes)
    if len(frame) != 28:
        raise ValueError("Data must be exactly 28 bytes long")

    # Parse data
    data_buffer = []
    pos = 0
    while pos < len(frame):
        # Extract 5 bytes
        packed = frame[pos : pos + 5]
        if len(packed) < 5:
            break

        # Convert 5 bytes into four 10-bit numbers
        b0, b1, b2, b3, b4 = packed
        data_buffer.append((b0 << 2) | (b1 >> 6))
        data_buffer.append(((b1 & 0x3F) << 4) | (b2 >> 4))
        data_buffer.append(((b2 & 0x0F) << 6) | (b3 >> 2))
        data_buffer.append(((b3 & 0x03) << 8) | b4)

        pos += 5

    if len(data_buffer) != 16:
        pass

    # This is the way to calculate the relative scan count
    return (data_buffer[5] << 10) | data_buffer[6]


def modify_relative_scan_count(old_line_header: bytes, new_line_count: int) -> bytes:
    """Changes the relative scan count inside a frame using black magic

    Args:
        old_line_header (bytes): The line header to modify
        new_line_count (int): The line count to change this one to

    Returns:
        bytes: The new line header containing the updated line count
    """
    # Initial decoding of the data array
    data_buffer = [0] * 16
    pos = 0
    for i in range(0, 16, 4):
        data_buffer[i] = (old_line_header[pos + 0] << 2) | (
            old_line_header[pos + 1] >> 6
        )
        data_buffer[i + 1] = ((old_line_header[pos + 1] % 64) << 4) | (
            old_line_header[pos + 2] >> 4
        )
        data_buffer[i + 2] = ((old_line_header[pos + 2] % 16) << 6) | (
            old_line_header[pos + 3] >> 2
        )
        data_buffer[i + 3] = ((old_line_header[pos + 3] % 4) << 8) | old_line_header[
            pos + 4
        ]
        pos += 5

    # Modify the counter
    data_buffer[5] = (new_line_count >> 10) & 0xFFFF  # Upper 10 bits
    data_buffer[6] = new_line_count & 0x3FF  # Lower 10 bits

    # Re-encode the data array
    new_line_header = bytearray(28)
    pos = 0
    for i in range(0, 16, 4):
        new_line_header[pos + 0] = (data_buffer[i] >> 2) & 0xFF
        new_line_header[pos + 1] = ((data_buffer[i] & 0x3) << 6) | (
            (data_buffer[i + 1] >> 4) & 0x3F
        )
        new_line_header[pos + 2] = ((data_buffer[i + 1] & 0xF) << 4) | (
            (data_buffer[i + 2] >> 6) & 0xF
        )
        new_line_header[pos + 3] = ((data_buffer[i + 2] & 0x3F) << 2) | (
            (data_buffer[i + 3] >> 8) & 0x3
        )
        new_line_header[pos + 4] = data_buffer[i + 3] & 0xFF
        pos += 5

    return new_line_header


# - MAIN CODE -

with open(input_file, "rb") as original_file, open(output_file, "wb") as corrected_file:
    data = original_file.read()

    # Is assigned when the current imagery series had N/10 matching counters
    consistent_line_counter = None

    # Block_series structure:
    # NAME = BLOCK ID
    #   -> frame: Full frame that contained this block
    #   -> counter: Current block's line count
    block_series = {}

    # Caches useless frames (Block-ID 11) for writing
    unmodified_frames = []

    # The program exits when it can't parse a header anymore, otherwise it'll loop indefinitely.
    while FRAME_LIMIT > CURRENT_FRAME:
        TOTAL_FRAME_COUNT += 1
        CURRENT_FRAME += 1

        # One frame is 32786 bytes long
        OFFSET = CURRENT_FRAME * 32786
        FRAME = data[CURRENT_FRAME * 32786 : CURRENT_FRAME * 32786 + 32786]
        header = get_header(FRAME)

        # Skips erroneous headers - Only 0-11 are valid IDs, 0 is unused by SatDump
        # Some fixing might be possible here - maybe by checking for a missing block from a series?
        if header[0] == 0 or header[0] > 11:
            continue

        # Block 11 (Auxiliary) can be skipped, since we aren't correcting it
        if header[0] == 11:
            LAST_BLOCK_ID = 11
            unmodified_frames.append(FRAME)
            continue

        # 28 bytes long
        current_count = get_line_counter_from_frame(FRAME[98:126])

        # Are we starting a new imagery series?
        # - Was the previous block the last one of the previous series or ignored (11)?
        # - Is the current block already in the series?
        # This should cover most cases

        # Let the fun begin!
        if block_series and (LAST_BLOCK_ID in [10, 11] or header[0] in block_series):

            # Correction type 1) Consistency based correction
            # Blocks 1-10 are sent sequentially, and every one of these has a line counter. We can check if
            # a counter matches in at least N/10 of these. If so, we can assume it is definitely correct
            # and hence expect the next one to be this one +1

            if (
                consistent_line_counter
                and len(set([block["counter"] for block in block_series.values()])) > 1
            ):

                # This can be added back in for additional safety. -> It only executes correction if
                # it's present in the next series, removing this protects from the rare cases where
                # **ALL** counters are incorrect.
                # and (consistent_line_counter+1) in set([block["counter"] for block in block_series.values()])\

                print(
                    "> Correcion is needed, the last series had a consistent counter!"
                    + f" ({consistent_line_counter})"
                )

                for block_id, block in block_series.items():
                    if block["counter"] == consistent_line_counter + 1:
                        continue
                    # 1) Get the frame containing the damaged line header
                    incorrect_frame = block["frame"]

                    # 2) Replace the incorrect counter with the correct one
                    corrected_line_header = modify_relative_scan_count(
                        incorrect_frame[98:126], consistent_line_counter + 1
                    )

                    # 3) Replace the frame with the corrected one
                    corrected_frame = (
                        incorrect_frame[:98]
                        + corrected_line_header
                        + incorrect_frame[126:]
                    )
                    block["frame"] = corrected_frame

                    # 4) Verify it corrected properly by parsing the corrected frame
                    new_counter = get_line_counter_from_frame(corrected_frame[98:126])

                    # Sent for debug purposes
                    print(
                        f"Corrected ID {block_id}! Old counter: {block['counter']} New counter: {new_counter}"
                    )

                    # This shouldn't happen.
                    if new_counter != consistent_line_counter + 1:
                        raise ValueError(
                            "The new counter doesn't match the correct one!"
                        )

            # Correction 2) Majority law within block series
            # We set all the counter to the most common one, as it is the likeliest to be true.
            # This is only used as a fallback if a consistent counter wasn't detected in the
            # last series. It can also be used on its own at basically no difference.
            elif len(set([block["counter"] for block in block_series.values()])) > 1:
                print(
                    f'> Correction is needed, but a consistent counter wasn\'t detected. Falling back with values: {set([block_series[x]["counter"] for x in block_series])} !!! ---'
                )
                # 1) Get the correct counter number
                correct_counter = max(
                    set([block_series[x]["counter"] for x in block_series]),
                    key=[block_series[x]["counter"] for x in block_series].count,
                )

                # 2) Iterate through blocks, look for ones with invalid counters
                for block_id, block in block_series.items():

                    # 3) Check if this block has an incorrect counter
                    if block["counter"] != correct_counter:
                        print(f"Block with ID {block_id} is incorrect! Correcting...")

                        # 4) Get the frame containing the damaged line header
                        incorrect_frame = block["frame"]

                        # 5) Replace the incorrect counter with the correct one
                        corrected_line_header = modify_relative_scan_count(
                            incorrect_frame[98:126], correct_counter
                        )

                        # 6) Replace the frame with the corrected one
                        corrected_frame = (
                            incorrect_frame[:98]
                            + corrected_line_header
                            + incorrect_frame[126:]
                        )
                        block["frame"] = corrected_frame

                        # 7) Verify it corrected properly by parsing the corrected frame
                        new_counter = get_line_counter_from_frame(
                            corrected_frame[98:126]
                        )

                        # Sent for debug purposes
                        print(
                            f"Corrected ID {block_id}! Old counter: {block['counter']} New counter: {new_counter}"
                        )

                        # This shouldn't happen.
                        if new_counter != correct_counter:
                            raise ValueError(
                                "The new counter doesn't match the correct one!"
                            )

            # Everything checks out, all values match.
            else:
                print(f"> Nothing to do with this series.")

            # Looks for a consistent counter in this block. The counter isn't changed in
            # block_series, so we can use it even though the frames have been fixed.
            most_common_counter = max(
                set([block["counter"] for block in block_series.values()]),
                key=[block["counter"] for block in block_series.values()].count,
            )

            if [block["counter"] for block in block_series.values()].count(
                most_common_counter
            ) > CONSISTENCY_CHECK:
                print(
                    f"{consistent_line_counter}+1 = {most_common_counter}, it is present {[block['counter'] for block in block_series.values()].count(most_common_counter)} times!"
                )
                consistent_line_counter = most_common_counter

            # No consistent counter was found.
            else:
                most_common_amount = [
                    block["counter"] for block in block_series.values()
                ].count(most_common_counter)

                # Used for debugging.
                print(
                    f"This series won't produce a consistent counter, {consistent_line_counter}+1 = {most_common_counter}, which is present {most_common_amount} times while the minimum is set to {CONSISTENCY_CHECK+1}"
                )
                consistent_line_counter = None

            # After fixing all counters, we can write to the output file

            # Writes imagery (Block-ID 1-10)
            for block in block_series:
                corrected_file.write(block_series[block]["frame"])

            # Writes auxiliary data (Block-ID 11)
            for block in unmodified_frames:
                corrected_file.write(block)

            # Resets for next block series
            block_series = {}
            unmodified_frames = []

            # Just used to separate the console output nicely
            print("---")

        # We are currently in a block series, save the current block data for later checking
        block_series[header[0]] = {
            "frame": FRAME,  # Start of line header in data
            "counter": current_count,  # Current line count
        }

        # Can be uncommented for more verbose logging.
        # print(
        #    f'{"ID:":2s} {header[0]:3d} {"Block count:":2s} {int.from_bytes(header[12:13])} {"Counter:":2s} {current_count}'
        # )

        # Saves the last ID to verify we won't start a new series
        LAST_BLOCK_ID = header[0]

# Gets executed when a manual limit is set
exit_gracefully()
