# To-do list

This is probably the only fully non-LLM written file here. :D 

RSBViewer: 

- Integrate the png2rsb writer.
- Implement image preview mode (I have a working prototype on my pc, I need to upload it.)
  On that note, I need to make the image preview 'auto display', as right now it's "select .rsb file, click button to preview", which I don't want.
- Move the RSBViewer from just a scrollable list to a more 'Editable'/selectable list where values can be added and changed, etc. Overall improve the layout.
  Then feed those into command-line arguments to PNG2RSB.py

PNG2RSB:
 - More testing of the output this tool produces. So far many of the items open up in RSBEditor with their correct settings, so the flags are being set correctly.
  Just need to test it in-game.

 - Need to improve the number of options (the subsampling priority option is only 0-3, it should be 0-4), animation type 0 is not 'none', for example.
 - Need to actually test how RSBEditor's 'distortion map generator' works.
 - Friendly names for the surface type, right now it's just 'insert a number from 0 to 26' when it should display Sand, Wood, Metal, etc.
 
RSB2PNG:
 - Nothing off the top of my head here, it does exactly what other tools like AlexKimov's Noesis plugin does, just reads the image data and spits out a png.
   I'd like to eventually have something that could save the existing metadata footer that comes after the image on a per file basis, so the 'original' settings of
   the converted RSB could be reapplied. But that's a 'nice to have'.

And if you're still reading this, I hope you find the tools useful!

Count_Fuzzball.
