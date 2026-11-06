"""Summary and full human output for the instruction roster."""

from __future__ import annotations


def instruction_list_writer(args, render_descriptors):
    full = "--full" in args

    def write(response, stdout, stderr):
        del stderr
        instructions = (response.result or {}).get("instructions") or []
        if not instructions:
            stdout.write(render_descriptors([]))
            return
        descriptors = []
        for instruction in instructions:
            content = str(instruction.get("content") or "")
            title = content.splitlines()[0] if content else ""
            descriptors.append({**instruction, "title": title})
            if full:
                print(f"## {instruction.get('id')} {title}", file=stdout)
                print(content, file=stdout)
                print(file=stdout)
        if full:
            return
        read = "yoke workflow execution-instruction list --full"
        for descriptor in descriptors:
            descriptor["read"] = read
        stdout.write(render_descriptors(descriptors))

    return write
