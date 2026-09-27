import 'package:fitgains/core/wide_screen_wrapper.dart';
import 'package:fitgains/features/routines/widgets/plate_calculator.dart';
import 'package:fitgains/l10n/generated/app_localizations.dart';
import 'package:material_ui/material_ui.dart';

class ConfigurePlatesScreen extends StatelessWidget {
  static const routeName = '/ConfigureAvailablePlates';

  const ConfigurePlatesScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final i18n = AppLocalizations.of(context);

    return Scaffold(
      appBar: AppBar(title: Text(i18n.selectAvailablePlates)),
      body: const WidescreenWrapper(child: ConfigureAvailablePlates()),
    );
  }
}
