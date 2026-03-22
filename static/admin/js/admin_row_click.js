(function ($) {
  $(document).ready(function () {
    $("#result_list tbody tr").each(function () {
      const link = $(this).find("th a")[0]; // First link in row (our id_link)
      if (link) {
        $(this).css("cursor", "pointer");
        $(this).on("click", function (e) {
          // Ignore if clicking a link/button/input inside row
          if (!$(e.target).closest("a, button, input, select").length) {
            window.location = link.href;
          }
        });
      }
    });
  });
})(django.jQuery);
