#
# ida_utilities.py
# Brandon Azad
#
# Some utility functions to make working with IDA easier.
#

import idc
import idautils
import idaapi

from collections import deque

WORD_SIZE = 0
"""The size of a word on the current platform."""

BIG_ENDIAN = False
"""Whether the current platform is big endian."""

LITTLE_ENDIAN = True
"""Whether the current platform is little-endian. Always the opposite of BIG_ENDIAN."""

def _initialize():
    # https://reverseengineering.stackexchange.com/questions/11396/how-to-get-the-cpu-architecture-via-idapython
    global WORD_SIZE, LITTLE_ENDIAN, BIG_ENDIAN
    info = idaapi.get_inf_structure()
    if info.is_64bit():
        WORD_SIZE = 8
    elif info.is_32bit():
        WORD_SIZE = 4
    else:
        WORD_SIZE = 2
    BIG_ENDIAN    = info.mf
    LITTLE_ENDIAN = not BIG_ENDIAN

_initialize()

def iterlen(iterator):
    """Consume an iterator and return its length."""
    return sum(1 for _ in iterator)

class AlignmentError(Exception):
    """An exception that is thrown if an address with improper alignment is encountered."""
    def __init__(self, address):
        self.address = address
    def __str__(self):
        return repr(self.address)

def is_mapped(ea, size=1):
    """Check if the given address is mapped.

    Specify a size greater than 1 to check if an address range is mapped.
    """
    # HACK: We only check the first and last byte, not all the bytes in between.
    return idc.isLoaded(ea) and (size > 1 or idc.isLoaded(ea + size - 1))

def set_name(ea, name, rename=False):
    """Set the name of an address.

    Arguments:
        ea: The address to name.
        name: The new name of the address.

    Options:
        rename: If rename is False, and if the address already has a name, and if that name differs
            from the new name, then this function will fail. Set rename to True to rename the
            address even if it already has a custom name. Default is False.

    Returns:
        True if the address was successfully named (or renamed).
    """
    if not rename and idc.hasUserName(idc.GetFlags(ea)):
        current_name = idc.NameEx(idc.BADADDR, ea)
        return current_name == name
    return bool(idc.MakeName(ea, name))

def _addresses(start, end, step, partial, aligned):
    """A generator to iterate over the addresses in an address range.

    Internal use only.
    """
    addr = start
    end_full = end - step + 1
    while addr < end_full:
        yield addr
        addr += step
    if addr != end:
        if aligned:
            raise AlignmentError(end)
        if addr < end and partial:
            yield addr

def _mapped_addresses(addresses, step, partial, allow_unmapped):
    """Wrap an _addresses generator with a filter that checks whether the addresses are mapped.

    Internal use only.
    """
    for addr in addresses:
        start_is_mapped = is_mapped(addr)
        end_is_mapped   = is_mapped(addr + step - 1)
        fully_mapped    = start_is_mapped and end_is_mapped
        allowed_partial = partial and (start_is_mapped or end_is_mapped)
        # Yield the value if it's sufficiently mapped. Otherwise, break if we stop at an
        # unmapped address.
        if fully_mapped or allowed_partial:
            yield addr
        elif not allow_unmapped:
            break

def Addresses(start, end=None, step=1, length=None, partial=False, aligned=False,
        unmapped=False, allow_unmapped=False):
    """A generator to iterate over the addresses in an address range.

    Arguments:
        start: The start of the address range to iterate over.

    Options:
        end: The end of the address range to iterate over.
        step: The amount to step the address by each iteration. Default is 1.
        length: The number of elements of size step to iterate over.
        partial: If only part of the element is in the address range, or if only part of the
            element is mapped, return it anyway. Default is False. This option is only meaningful
            if aligned is False or if some address in the range is partially unmapped.
        aligned: If the end address is not aligned with an iteration boundary, throw an
            AlignmentError.
        unmapped: Don't check whether an address is mapped or not before returning it. This option
            always implies allow_unmapped. Default is False.
        allow_unmapped: Don't stop iteration if an unmapped address is encountered (but the address
            won't be returned unless unmapped is also True). Default is False. If partial is also
            True, then a partially mapped address will be returned and then iteration will stop.
    """
    # HACK: We only check the first and last byte, not all the bytes in between.
    # Validate step.
    if step < 1:
        raise ValueError('Invalid arguments: step={}'.format(step))
    # Set the end address.
    if length is not None:
        end_addr = start + length * step
        if end is not None and end != end_addr:
            raise ValueError('Invalid arguments: start={}, end={}, step={}, length={}'
                    .format(start, end, step, length))
        end = end_addr
    if end is None:
        raise ValueError('Invalid arguments: end={}, length={}'.format(end, length))
    addresses = _addresses(start, end, step, partial, aligned)
    # If unmapped is True, iterate over all the addresses. Otherwise, we will check that addresses
    # are properly mapped with a wrapper.
    if unmapped:
        return addresses
    else:
        return _mapped_addresses(addresses, step, partial, allow_unmapped)

def Instructions(start, end):
    """A generator to iterate over the instructions in the given address range.

    Instructions are decoded using IDA's DecodeInstruction(). If the end of the address range does
    not fall on an instruction boundary, raises an AlignmentError.
    """
    pc = start
    while pc < end:
        insn = idautils.DecodeInstruction(pc)
        if insn is None:
            break
        next_pc = pc + insn.size
        if next_pc > end:
            raise AlignmentError(end)
        yield insn
        pc = next_pc

def read_word(ea, wordsize=WORD_SIZE):
    """Get the word at the given address.

    Words are read using Byte(), Word(), Dword(), or Qword(), as appropriate. Addresses are checked
    using is_mapped(). If the address isn't mapped, then None is returned.
    """
    if not is_mapped(ea, wordsize):
        return None
    if wordsize == 1:
        return idc.Byte(ea)
    if wordsize == 2:
        return idc.Word(ea)
    if wordsize == 4:
        return idc.Dword(ea)
    if wordsize == 8:
        return idc.Qword(ea)
    assert wordsize in (1, 2, 4, 8)

def ReadWords(start, end, wordsize=WORD_SIZE, addresses=False):
    """A generator to iterate over the data words in the given address range.

    The iterator returns a stream of words or tuples for each mapped word in the address range.
    Words are read using read_word(). Iteration stops at the first unmapped word.

    Arguments:
        start: The start address.
        end: The end address.

    Options:
        wordsize: The word size to read, in bytes. Default is WORD_SIZE.
        addresses: If true, then the iterator will return a stream of tuples (word, ea) for each
            mapped word in the address range. Otherwise, just the word itself will be returned.
            Default is False.
    """
    for addr in Addresses(start, end, step=wordsize, unmapped=True):
        word = read_word(addr, wordsize)
        if word is None:
            break
        value = (word, addr) if addresses else word
        yield value

def WindowWords(start, end, window_size, wordsize=WORD_SIZE):
    """A generator to iterate over a sliding window of data words in the given address range.

    The iterator returns a stream of tuples (window, ea) for each word in the address range. The
    window is a deque of the window_size words at address ea. The deque is owned by the generator
    and its contents will change between iterations.
    """
    words = ReadWords(start, end, wordsize=wordsize)
    window = deque([next(words) for _ in range(window_size)], maxlen=window_size)
    addr = start
    yield window, addr
    for word in words:
        window.append(word)
        addr += wordsize
        yield window, addr

