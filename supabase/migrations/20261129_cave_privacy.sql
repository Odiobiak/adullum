-- The cave is private.
--
-- Until now every journal entry and prayer became a note in Aquila's memory,
-- so Aquila on the Aquila page could bring up something written in the cave.
-- Now each entry carries a choice: Aquila outside the cave sees it only when
-- the person switches on "Let Aquila see this". Aquila in Refuge, inside the
-- cave, still sees the journal and the prayer list (app/refuge.py::cave_notes).
--
-- Run once, after the others. Until it runs, the journal and the prayer list
-- work with every entry private, and the switch says to run this.
begin;

alter table journal_entries add column if not exists aquila_sees boolean not null default false;
alter table prayers add column if not exists aquila_sees boolean not null default false;

-- Notes taken from entries before anyone was asked. Each comes back when its
-- entry is let in (app/cave.py::_remember_journal, app/prayers.py::_remember).
delete from user_memories where kind in ('journal', 'prayer');

commit;
