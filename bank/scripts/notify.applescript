on run argv
	-- Args arrive as literal AppleScript values (osascript argv passing),
	-- never string-interpolated into the script source, so notification
	-- text can't inject AppleScript.
	set msg to item 1 of argv
	if (count of argv) > 1 then
		set t to item 2 of argv
	else
		set t to "consumer"
	end if
	display notification msg with title t
end run