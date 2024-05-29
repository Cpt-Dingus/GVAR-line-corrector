# Made by Cpt-Dingus
# v1.0 - 29/05/2024

import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument("-o", "--output")
parser.add_argument("-i", "--input")
input_file = parser.parse_args().input
output_file = parser.parse_args().output

# These start at -1 to ensure the first frame is processed
CURRENT_FRAME = 0
TOTAL_FRAME_COUNT = 0
# Can be lowered for testing if you don't want the whole file to be processed
FRAME_LIMIT = 250000
LAST_BLOCK_ID = 0


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
            #     SYNC   HEADER START  SYNC    HEADER START       HEADER END (30 bytes long)
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


with open(input_file, "rb") as original_file, open(output_file, "wb") as corrected_file:
    data = original_file.read()

    # Block_series structure:
    # NAME = BLOCK ID
    #   -> frame: Full frame that contained this count
    #   -> counter: Current line count
    block_series = {}

    # Caches useless frames (Block-ID 11) for writing
    unmodified_frames = []

    while FRAME_LIMIT > CURRENT_FRAME:
        TOTAL_FRAME_COUNT += 1
        CURRENT_FRAME += 1

        # One frame is 32786 bytes long
        OFFSET = CURRENT_FRAME * 32786
        FRAME = data[CURRENT_FRAME * 32786 : CURRENT_FRAME * 32786 + 32786]
        header = get_header(FRAME)

        # Skips erroneous headers - Only 0-11 are valid IDs, 0 is unused by SatDump
        # Some fixing might be possible here - aybe by checking for a missing block from a series?
        if header[0] == 0 or header[0] > 11:
            continue

        # Block 11 (Auxiliary) can be skipped, since we aren't correcting it
        if header[0] == 11:
            LAST_BLOCK_ID = 11
            unmodified_frames.append(FRAME)
            continue

        # 28 bytes long
        current_count = get_line_counter_from_frame(FRAME[98:126])

        # Are we starting a new series?
        # - Was the last block the last block from the series or ignored (11)?
        # - Is the current block already in the series?
        # This should cover most cases
        if LAST_BLOCK_ID in [10, 11] or header[0] in block_series:

            # A series was completed, check if bad counters are present
            if len(set([block_series[x]["counter"] for x in block_series])) != 1:

                print(
                    f"--- !!! Counter set is invalid, correction is needed for this series! Values: {set([block_series[x]["counter"] for x in block_series])} !!! ---"
                )

                # 0) Get the correct counter number
                correct_counter = max(
                    set([block_series[x]["counter"] for x in block_series]),
                    key=[block_series[x]["counter"] for x in block_series].count,
                )

                # 1) Iterate through blocks, look for ones with invalid counters
                for block in block_series:

                    if block_series[block]["counter"] != correct_counter:
                        print(f"Block with ID {block} is incorrect! Correcting...")

                        # 3) Get the frame containing the damaged line header
                        incorrect_frame = block_series[block]["frame"]

                        # 4) Replace the incorrect counter with the correct one

                        # NOTE: This could be done another way, that's by checking if the previous
                        # counter + 1 matches this one. If it doesn't, we could replace this one
                        # with the last one + 1. Maybe only do this when 5/10 counters matched
                        # or something? It's more likely to be correct then
                        corrected_line_header = modify_relative_scan_count(
                            incorrect_frame[98:126], correct_counter
                        )

                        # 5) Replace the frame with the corrected one
                        corrected_frame = (
                            incorrect_frame[:98]
                            + corrected_line_header
                            + incorrect_frame[126:]
                        )
                        block_series[block]["frame"] = corrected_frame

                        # 6) Verify it corrected properly by parsing the corrected frame
                        new_counter = get_line_counter_from_frame(
                            corrected_frame[98:126]
                        )

                        # Sent for debug purposes
                        print(
                            f"Corrected ID {block}! Old counter: {block_series[block]["counter"]} New counter: {new_counter}"
                        )

                        # This shouldn't happen.
                        if new_counter != correct_counter:
                            raise ValueError(
                                "The new counter doesn't match the correct one!"
                            )

            # 7) After fixing all counters, we can write to the output file

            # Writes imagery (Block-ID 1-10)
            for block in block_series:
                corrected_file.write(block_series[block]["frame"])

            # Writes auxiliary data (Block-ID 11)
            for block in unmodified_frames:
                corrected_file.write(block)

            # Resets for next image series
            block_series = {}
            unmodified_frames = []

            # Just used to separate the console output nicely
            print("---")

        # We are currently in a block series, save the current block data for later checking
        block_series[header[0]] = {
            "frame": FRAME,  # Start of line header in data
            "counter": current_count,  # Current line count
        }

        print(
            f'{"ID:":2s} {header[0]:3d} {"Block count:":2s} {int.from_bytes(header[12:13])} {"Counter:":2s} {current_count}'
        )

        # Saves the last ID to verify we won't start a new series
        LAST_BLOCK_ID = header[0]
